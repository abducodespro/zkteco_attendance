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


# ─────────────────────────────────────────────────────────────────────────────
# Realtime progress helper
# ─────────────────────────────────────────────────────────────────────────────

def _emit_progress(device_name, user, stage, current=0, total=0, message="", extra=None):
    """
    Publish a realtime event so the Biometric Device form can show a live
    progress bar while 'Pull Checkins' is running.
    Safe to call even outside a request (errors are swallowed).
    """
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
        frappe.publish_realtime(
            event="zkteco_pull_progress",
            message=payload,
            user=user,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Employee lookup
# ─────────────────────────────────────────────────────────────────────────────

def get_employee_by_biometric_id(user_id, company=None):
    """
    Find ERPNext Employee by biometric attendance ID.
    Uses the 'attendance_device_id' custom field on Employee.
    """
    filters = {"attendance_device_id": str(user_id), "status": "Active"}
    if company:
        filters["company"] = company

    employees = frappe.get_all(
        "Employee", filters=filters,
        fields=["name", "employee_name", "company"]
    )
    if employees:
        return employees[0]

    # Fallback: search without company restriction
    if company:
        employees = frappe.get_all(
            "Employee",
            filters={"attendance_device_id": str(user_id), "status": "Active"},
            fields=["name", "employee_name", "company"]
        )
        if employees:
            return employees[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate check
# ─────────────────────────────────────────────────────────────────────────────

def checkin_exists(employee, timestamp, log_type, device_name):
    """
    Duplicate check: return True if a matching checkin already exists
    within a ±60 second window.
    Uses raw SQL for v14/v15/v16 compatibility (no SQL-expression filter keys).
    """
    ts = get_datetime(timestamp)
    ts_from = ts - timedelta(seconds=60)
    ts_to   = ts + timedelta(seconds=60)

    result = frappe.db.sql(
        """SELECT name FROM `tabEmployee Checkin`
           WHERE employee = %s
             AND log_type = %s
             AND `time` BETWEEN %s AND %s
             AND device_id = %s
           LIMIT 1""",
        (employee, log_type, ts_from, ts_to, device_name)
    )
    return bool(result)


def raw_record_already_pulled(device_name, uid):
    """
    Return True if a raw device record (identified by its device-local uid)
    has already been pulled before. Used for 'New Records Only' fetch mode
    and to avoid reprocessing the same punch on every sync.
    """
    if uid is None:
        return False
    result = frappe.db.sql(
        """SELECT name FROM `tabEmployee Checkin`
           WHERE device_id = %s AND zk_uid = %s
           LIMIT 1""",
        (device_name, str(uid))
    )
    return bool(result)


# ─────────────────────────────────────────────────────────────────────────────
# Log type resolution (handles devices that send punch=0 for every punch)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_log_types_for_day(day_records):
    """
    Given a chronologically-sorted list of raw punch records (dicts with
    at least 'punch' and 'timestamp') for ONE employee on ONE calendar
    day, return a parallel list of resolved log_types ("IN"/"OUT" or
    "OUT" for overtime variants handled separately by the caller).

    Many ZKTeco devices/firmwares send punch=0 (Check In) for EVERY
    fingerprint/face punch — including the end-of-shift checkout — because
    the device itself has no concept of shift state. If we trusted
    `get_punch_type()` alone, a two-punch shift (clock in, clock out)
    would create TWO 'IN' Employee Checkins and ERPNext would never close
    the shift.

    To fix this, regular (non-OT) punches on the same day are alternated
    IN, OUT, IN, OUT, ... in chronological order — the standard convention
    used by most biometric attendance integrations. Explicit OT punches
    (device codes 4/5) are NOT part of this alternation; they keep their
    own IN/OUT meaning from `get_punch_type()`.
    """
    resolved = []
    regular_seq = 0  # counts only non-OT punches, 0-based

    for rec in day_records:
        punch = rec.get("punch")
        if is_overtime_punch(punch):
            # OT punches keep their explicit meaning (4 -> IN, 5 -> OUT)
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
    """Create a single Employee Checkin record."""
    checkin = {
        "doctype": "Employee Checkin",
        "employee": employee,
        "employee_name": employee_name,
        "time": timestamp,
        "log_type": log_type,
        "device_id": device_name,
    }

    # zk_uid and is_overtime are custom fields added on install (v14/v15/v16
    # compatible custom fields, so this works even if the standard
    # Employee Checkin doctype hasn't added native columns for these).
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

def sync_device(device_name, triggered_by="Manual", user=None):
    """
    Full sync for a single device:
    1. Pull records from device (with live progress events)
    2. Resolve IN/OUT (and overtime) log types per employee/day
    3. Map to ERPNext employees
    4. Create Employee Checkin records
    5. Log result to Attendance Sync Log
    6. Update last_sync_time on the device
    """
    device = frappe.get_doc("Biometric Device", device_name)
    user = user or frappe.session.user

    if device.status != "Active":
        _emit_progress(device_name, user, "error", message=_("Device is not Active"))
        return {"success": False, "error": "Device is not Active"}

    sync_start = now_datetime()
    total_records = 0
    new_records   = 0
    duplicates    = 0
    failed        = 0
    overtime_records = 0
    errors        = []

    def _progress_cb(stage, current, total, message):
        _emit_progress(device_name, user, stage, current, total, message)

    # ── Step 1: Pull raw records ────────────────────────────────────────────
    try:
        records = pull_attendance_from_device(
            device, fetch_mode=device.fetch_mode or "All Records",
            progress_callback=_progress_cb,
        )
        total_records = len(records)
    except Exception as e:
        _emit_progress(device_name, user, "failed", message=str(e))
        _save_sync_log(
            device=device_name,
            start_time=sync_start,
            end_time=now_datetime(),
            total=0, created=0, dupes=0, failed=0, overtime=0,
            status="Failed",
            error=str(e),
            triggered_by=triggered_by,
        )
        frappe.db.set_value("Biometric Device", device_name, "status", "Inactive")
        frappe.db.commit()
        return {"success": False, "error": str(e)}

    if device.fetch_mode == "New Records Only":
        before = len(records)
        records = [r for r in records if not raw_record_already_pulled(device_name, r.get("uid"))]
        _emit_progress(
            device_name, user, "filtered", len(records), before,
            _("Skipping {0} already-pulled record(s); {1} new record(s) to process.")
            .format(before - len(records), len(records))
        )

    # ── Step 2: Group by employee/day and resolve IN/OUT sequencing ─────────
    enable_ot = cint(getattr(device, "enable_overtime_punches", 1))

    grouped = {}
    for rec in records:
        ts = get_datetime(rec["timestamp"])
        key = (str(rec["user_id"]), ts.date())
        grouped.setdefault(key, []).append(rec)

    resolved_log_type = {}  # id(rec) -> log_type
    for (_user_id, _day), day_records in grouped.items():
        day_records_sorted = sorted(day_records, key=lambda r: get_datetime(r["timestamp"]))
        if enable_ot:
            log_types = resolve_log_types_for_day(day_records_sorted)
        else:
            # Overtime disabled: ignore OT punch codes, alternate everything
            log_types = []
            seq = 0
            for _r in day_records_sorted:
                log_types.append("IN" if seq % 2 == 0 else "OUT")
                seq += 1

        for rec, lt in zip(day_records_sorted, log_types):
            resolved_log_type[id(rec)] = lt

    # ── Step 3: Create Employee Checkins ────────────────────────────────────
    total_to_process = len(records)
    for idx, rec in enumerate(records, start=1):
        try:
            user_id   = str(rec["user_id"])
            timestamp = rec["timestamp"]
            punch     = rec.get("punch")

            log_type   = resolved_log_type.get(id(rec), get_punch_type(punch))
            is_ot      = bool(enable_ot and is_overtime_punch(punch))

            emp = get_employee_by_biometric_id(user_id, company=device.company)
            if not emp:
                failed += 1
                errors.append("No employee found for biometric ID: {}".format(user_id))
                continue

            if checkin_exists(emp["name"], timestamp, log_type, device_name):
                duplicates += 1
                continue

            create_employee_checkin(
                emp["name"], emp["employee_name"], timestamp, log_type, device_name,
                uid=rec.get("uid"), is_overtime=is_ot,
            )
            new_records += 1
            if is_ot:
                overtime_records += 1

        except Exception as e:
            failed += 1
            errors.append("uid={}: {}".format(rec.get("uid"), str(e)))
            frappe.log_error(
                message="Failed checkin for device {}, uid {}: {}".format(
                    device_name, rec.get("uid"), str(e)
                ),
                title="ZKTeco Checkin Error"
            )

        if idx % 10 == 0 or idx == total_to_process:
            _emit_progress(
                device_name, user, "creating_checkins", idx, total_to_process,
                _("Creating Employee Checkins: {0} of {1}").format(idx, total_to_process),
                extra={
                    "new_records": new_records,
                    "duplicates": duplicates,
                    "failed": failed,
                    "overtime_records": overtime_records,
                },
            )

    sync_end    = now_datetime()
    sync_status = "Success" if failed == 0 else ("Partial" if new_records > 0 else "Failed")

    _save_sync_log(
        device=device_name,
        start_time=sync_start,
        end_time=sync_end,
        total=total_records,
        created=new_records,
        dupes=duplicates,
        failed=failed,
        overtime=overtime_records,
        status=sync_status,
        error="\n".join(errors[:50]) if errors else "",
        triggered_by=triggered_by,
    )

    frappe.db.set_value("Biometric Device", device_name, {
        "last_sync_time": sync_end,
        "status": "Active",
    })
    frappe.db.commit()

    result = {
        "success": True,
        "total_records": total_records,
        "new_records":   new_records,
        "duplicates":    duplicates,
        "failed":        failed,
        "overtime_records": overtime_records,
        "sync_status":   sync_status,
        "errors":        errors[:20],
    }

    _emit_progress(device_name, user, "done", total_to_process, total_to_process,
                    _("Sync completed."), extra=result)

    return result


def sync_all_active_devices(frequency_filter=None, triggered_by="Scheduler"):
    """
    Sync all active devices, optionally filtered by sync_frequency.
    """
    filters = {"status": "Active", "auto_sync_enabled": 1}
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
            frappe.log_error(
                message="Scheduler sync failed for {}: {}".format(d["name"], str(e)),
                title="ZKTeco Scheduler Error"
            )
            results.append({"device": d["name"], "success": False, "error": str(e)})

    return results


def _save_sync_log(device, start_time, end_time, total, created,
                   dupes, failed, status, error, triggered_by, overtime=0):
    """Persist an Attendance Sync Log entry."""
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
            "sync_status": status,
            "error_details": error or "",
            "triggered_by": triggered_by,
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            message="Failed to save sync log for {}: {}".format(device, str(e)),
            title="ZKTeco Log Save Error"
        )
