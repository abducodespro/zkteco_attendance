"""
Sync Engine
Orchestrates pulling from devices, mapping employees, creating
Employee Checkin records, and logging results to Attendance Sync Log.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime, cint
from datetime import timedelta

from .zk_client import pull_attendance_from_device, get_punch_type, is_overtime_punch
from .attendance_processor import get_shift_for_employee, _coerce_time


# ─────────────────────────────────────────────────────────────────────────────
# Realtime progress helper
# ─────────────────────────────────────────────────────────────────────────────

def _emit_progress(device_name, user, stage, current=0, total=0, message="", extra=None):
    payload = {
        "device": device_name,
        "stage": stage,
        "current": current,
        "total": total,
        "message": message,
    }
    if extra:
        payload.update(extra)
    try:
        frappe.publish_realtime(event="zkteco_pull_progress", message=payload, user=user)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Employee lookup — now also matches by biometric device
# ─────────────────────────────────────────────────────────────────────────────

def get_employee_by_biometric_id(user_id, company=None, device_name=None):
    """
    Find ERPNext Employee by biometric attendance ID (attendance_device_id).
    Requires BOTH attendance_device_id AND zk_biometric_device to be set
    on the Employee — an employee without a mapped biometric device will
    not match, preventing accidental checkin pulls for unmapped employees.
    """
    if not device_name:
        return None

    base_filters = {
        "attendance_device_id": str(user_id),
        "zk_biometric_device": device_name,
        "status": "Active",
    }
    if company:
        base_filters["company"] = company

    emps = frappe.get_all("Employee", filters=base_filters,
                          fields=["name", "employee_name", "company"])
    if emps:
        return emps[0]

    # Retry without company filter (same device required)
    if company:
        emps = frappe.get_all("Employee",
                              filters={
                                  "attendance_device_id": str(user_id),
                                  "zk_biometric_device": device_name,
                                  "status": "Active",
                              },
                              fields=["name", "employee_name", "company"])
        if emps:
            return emps[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate check against DB
# ─────────────────────────────────────────────────────────────────────────────

def checkin_exists(employee, timestamp, log_type, device_name):
    """Return True if a matching checkin exists within ±60s."""
    ts = get_datetime(timestamp)
    ts_from = ts - timedelta(seconds=60)
    ts_to   = ts + timedelta(seconds=60)
    result = frappe.db.sql(
        """SELECT name FROM `tabEmployee Checkin`
           WHERE employee=%s AND log_type=%s AND `time` BETWEEN %s AND %s
             AND device_id=%s LIMIT 1""",
        (employee, log_type, ts_from, ts_to, device_name)
    )
    return bool(result)


def raw_record_already_pulled(device_name, uid):
    """Return True if a raw device record uid has already been created."""
    if uid is None:
        return False
    result = frappe.db.sql(
        """SELECT name FROM `tabEmployee Checkin`
           WHERE device_id=%s AND zk_uid=%s LIMIT 1""",
        (device_name, str(uid))
    )
    return bool(result)


# ─────────────────────────────────────────────────────────────────────────────
# Double-punch detection (same employee, within 1 minute of previous punch)
# ─────────────────────────────────────────────────────────────────────────────

def filter_double_punches(records):
    """
    For records already grouped per employee, remove any punch that falls
    within 60 seconds of the previously-accepted punch for that employee.
    Returns (kept_records, double_punch_count).
    Operates on the flat list in-place style: processes chronologically
    per user_id, skipping punches within 60s of the last kept one.
    """
    # Sort all records by user_id then timestamp
    from datetime import datetime as dt_class

    def ts(r):
        v = r["timestamp"]
        if isinstance(v, dt_class):
            return v
        return get_datetime(v)

    sorted_recs = sorted(records, key=lambda r: (str(r["user_id"]), ts(r)))

    kept = []
    double_punches = 0
    last_ts_per_user = {}  # user_id -> last accepted timestamp

    for rec in sorted_recs:
        uid = str(rec["user_id"])
        rec_ts = ts(rec)
        last = last_ts_per_user.get(uid)
        if last is not None:
            diff = abs((rec_ts - last).total_seconds())
            if diff <= 60:
                double_punches += 1
                continue
        last_ts_per_user[uid] = rec_ts
        kept.append(rec)

    return kept, double_punches


# ─────────────────────────────────────────────────────────────────────────────
# Log type resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_log_types_for_day(day_records):
    """Alternate IN/OUT for non-OT punches; OT punches keep explicit type."""
    resolved = []
    regular_seq = 0
    for rec in day_records:
        punch = rec.get("punch")
        if is_overtime_punch(punch):
            resolved.append(get_punch_type(punch))
        else:
            resolved.append("IN" if regular_seq % 2 == 0 else "OUT")
            regular_seq += 1
    return resolved


# ─────────────────────────────────────────────────────────────────────────────
# Employee Checkin creation
# ─────────────────────────────────────────────────────────────────────────────

def create_employee_checkin(employee, employee_name, timestamp, log_type, device_name,
                             uid=None, is_overtime=False):
    checkin = {
        "doctype": "Employee Checkin",
        "employee": employee,
        "employee_name": employee_name,
        "time": timestamp,
        "log_type": log_type,
        "device_id": device_name,
    }
    if uid is not None:
        checkin["zk_uid"] = str(uid)
    if is_overtime:
        checkin["is_overtime"] = 1
    doc = frappe.get_doc(checkin)
    doc.insert(ignore_permissions=True)
    return doc.name


# ─────────────────────────────────────────────────────────────────────────────
# Main sync
# ─────────────────────────────────────────────────────────────────────────────

def group_records_by_attendance_date(records, device):
    """
    Group records by (user_id, attendance date) for IN/OUT resolution.

    Night-shift aware: a punch at or before the assigned shift's end time
    (i.e. early AM) is attributed to the previous calendar day, so an IN at
    17:03 on 01/01 and an OUT at 05:58 on 02/01 land in the same group and
    alternate correctly instead of each becoming the first (IN) punch of
    their own calendar day.

    Returns (grouped, emp_cache) where grouped is {(user_id, date): [rec,...]}
    and emp_cache maps user_id -> matched Employee dict (reused by Step 5 to
    avoid re-querying).
    """
    emp_cache = {}
    shift_cache = {}
    grouped = {}
    for rec in records:
        ts = get_datetime(rec["timestamp"])
        user_id = str(rec["user_id"])
        att_date = get_attendance_date_for_punch(user_id, ts, device, emp_cache, shift_cache)
        grouped.setdefault((user_id, att_date), []).append(rec)
    return grouped, emp_cache


def get_attendance_date_for_punch(user_id, timestamp, device, emp_cache, shift_cache):
    """
    Return the attendance date a punch belongs to.

    For night shifts, a punch in the early AM (at or before the shift end
    time) belongs to the previous calendar day's shift. Matches the
    attribution used by attendance_processor.group_checkins_by_date so the
    IN/OUT alternation here agrees with how hours are later computed.
    Falls back to the raw calendar date when no employee or no shift
    assignment is found.
    """
    if user_id not in emp_cache:
        emp_cache[user_id] = get_employee_by_biometric_id(
            user_id, company=device.company, device_name=device.name
        )
    emp = emp_cache.get(user_id)
    if not emp:
        return timestamp.date()

    cache_key = (emp["name"], timestamp.date())
    if cache_key not in shift_cache:
        shift_cache[cache_key] = get_shift_for_employee(emp["name"], timestamp.date()) or {}
    shift = shift_cache[cache_key]

    if shift.get("is_night_shift"):
        end_str = str(shift.get("end_time") or "06:00:00")
        end_t = _coerce_time(end_str)
        if timestamp.time() <= end_t:
            return (timestamp - timedelta(days=1)).date()
    return timestamp.date()


def sync_device(device_name, triggered_by="Manual", user=None):
    device = frappe.get_doc("Biometric Device", device_name)
    user = user or frappe.session.user

    if not device.enable:
        _emit_progress(device_name, user, "error", message=_("Device is not enabled"))
        return {"success": False, "error": "Device is not enabled"}

    sync_start = now_datetime()
    total_records    = 0
    new_records      = 0
    duplicates       = 0
    failed           = 0
    overtime_records = 0
    double_punches   = 0
    errors           = []

    def _progress_cb(stage, current, total, message):
        _emit_progress(device_name, user, stage, current, total, message)

    # ── Step 1: Pull raw records ───────────────────────────────────────────
    try:
        records = pull_attendance_from_device(
            device, fetch_mode=device.fetch_mode or "All Records",
            progress_callback=_progress_cb,
        )
        total_records = len(records)
    except Exception as e:
        _emit_progress(device_name, user, "failed", message=str(e))
        _save_sync_log(device=device_name, start_time=sync_start, end_time=now_datetime(),
                       total=0, created=0, dupes=0, failed=0, overtime=0, double_punches=0,
                       status="Failed", error=str(e), triggered_by=triggered_by)
        frappe.db.set_value("Biometric Device", device_name, "status", "Inactive")
        frappe.db.commit()
        return {"success": False, "error": str(e)}

    # ── Step 2: Filter already-pulled (New Records Only) ───────────────────
    if device.fetch_mode == "New Records Only":
        before = len(records)
        records = [r for r in records if not raw_record_already_pulled(device_name, r.get("uid"))]
        _emit_progress(device_name, user, "filtered", len(records), before,
                       _("Skipping {0} already-pulled; {1} new to process.")
                       .format(before - len(records), len(records)))

    # ── Step 3: Filter double punches (within 60s per employee) ───────────
    records, double_punches = filter_double_punches(records)
    if double_punches:
        _emit_progress(device_name, user, "deduped", len(records), total_records,
                       _("Removed {0} double punch(es) (same employee within 1 minute).")
                       .format(double_punches),
                       extra={"double_punches": double_punches})

    # ── Step 4: Resolve IN/OUT log types per employee/day ─────────────────
    enable_ot = cint(getattr(device, "enable_overtime_punches", 1))

    # Group by attendance date (night-shift aware) so an IN on 01/01 17:03
    # and an OUT on 02/01 05:58 belong to the same group and alternate
    # IN -> OUT instead of each becoming the first (IN) punch of the day.
    grouped, emp_cache = group_records_by_attendance_date(records, device)

    resolved_log_type = {}
    for (_user_id, _day), day_recs in grouped.items():
        day_recs_sorted = sorted(day_recs, key=lambda r: get_datetime(r["timestamp"]))
        if enable_ot:
            log_types = resolve_log_types_for_day(day_recs_sorted)
        else:
            log_types = ["IN" if i % 2 == 0 else "OUT" for i in range(len(day_recs_sorted))]
        for rec, lt in zip(day_recs_sorted, log_types):
            resolved_log_type[id(rec)] = lt

    # ── Step 5: Create Employee Checkins ──────────────────────────────────
    total_to_process = len(records)
    for idx, rec in enumerate(records, start=1):
        try:
            user_id   = str(rec["user_id"])
            timestamp = rec["timestamp"]
            punch     = rec.get("punch")
            log_type  = resolved_log_type.get(id(rec), get_punch_type(punch))
            is_ot     = bool(enable_ot and is_overtime_punch(punch))

            emp = emp_cache.get(user_id)
            if not emp:
                failed += 1
                errors.append("No employee for biometric ID: {}".format(user_id))
                continue

            if checkin_exists(emp["name"], timestamp, log_type, device_name):
                duplicates += 1
                continue

            create_employee_checkin(emp["name"], emp["employee_name"], timestamp,
                                    log_type, device_name, uid=rec.get("uid"), is_overtime=is_ot)
            new_records += 1
            if is_ot:
                overtime_records += 1

        except Exception as e:
            failed += 1
            errors.append("uid={}: {}".format(rec.get("uid"), str(e)))
            frappe.log_error(
                message="Failed checkin for device {}, uid {}: {}".format(
                    device_name, rec.get("uid"), str(e)),
                title="ZKTeco Checkin Error"
            )

        if idx % 10 == 0 or idx == total_to_process:
            _emit_progress(device_name, user, "creating_checkins", idx, total_to_process,
                           _("Creating Employee Checkins: {0} of {1}").format(idx, total_to_process),
                           extra={"new_records": new_records, "duplicates": duplicates,
                                  "failed": failed, "overtime_records": overtime_records,
                                  "double_punches": double_punches})

    sync_end    = now_datetime()
    sync_status = "Success" if failed == 0 else ("Partial" if new_records > 0 else "Failed")

    _save_sync_log(device=device_name, start_time=sync_start, end_time=sync_end,
                   total=total_records, created=new_records, dupes=duplicates,
                   failed=failed, overtime=overtime_records, double_punches=double_punches,
                   status=sync_status, error="\n".join(errors[:50]) if errors else "",
                   triggered_by=triggered_by)

    frappe.db.set_value("Biometric Device", device_name, {"last_sync_time": sync_end, "status": "Active"})
    frappe.db.commit()

    result = {
        "success": True,
        "total_records": total_records,
        "new_records": new_records,
        "duplicates": duplicates,
        "failed": failed,
        "overtime_records": overtime_records,
        "double_punches": double_punches,
        "sync_status": sync_status,
        "errors": errors[:20],
    }
    _emit_progress(device_name, user, "done", total_to_process, total_to_process,
                   _("Sync completed."), extra=result)
    return result


def sync_all_active_devices(frequency_filter=None, triggered_by="Scheduler"):
    filters = {"enable": 1, "auto_sync_enabled": 1}
    if frequency_filter:
        filters["sync_frequency"] = frequency_filter
    devices = frappe.get_all("Biometric Device", filters=filters, fields=["name"])
    results = []
    for d in devices:
        try:
            result = sync_device(d["name"], triggered_by=triggered_by)
            result["device"] = d["name"]
            results.append(result)
        except Exception as e:
            frappe.log_error(message="Scheduler sync failed for {}: {}".format(d["name"], str(e)),
                             title="ZKTeco Scheduler Error")
            results.append({"device": d["name"], "success": False, "error": str(e)})
    return results


def _save_sync_log(device, start_time, end_time, total, created, dupes, failed,
                   status, error, triggered_by, overtime=0, double_punches=0):
    try:
        log = frappe.get_doc({
            "doctype": "Attendance Sync Log",
            "device": device,
            "start_time": start_time,
            "end_time": end_time,
            "total_records_pulled": total,
            "new_records_created": created,
            "duplicate_records": dupes,
            "failed_records": failed,
            "overtime_records": overtime,
            "double_punch_records": double_punches,
            "sync_status": status,
            "error_details": error or "",
            "triggered_by": triggered_by,
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(message="Failed to save sync log for {}: {}".format(device, str(e)),
                         title="ZKTeco Log Save Error")
