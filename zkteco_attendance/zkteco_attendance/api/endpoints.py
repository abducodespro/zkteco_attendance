"""
Whitelisted API endpoints for ZKTeco Attendance.
These are callable from JavaScript / REST.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, nowdate, add_days, cint
from zkteco_attendance.zkteco_attendance.utils import has_column


@frappe.whitelist()
def test_connection(device_name):
    """Test connection to a biometric device and return device info."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])
    from zkteco_attendance.zkteco_attendance.zk_client import test_device_connection
    return test_device_connection(device_name)


@frappe.whitelist()
def pull_checkins_now(device_name):
    """
    Run a Pull Checkins sync IN THE FOREGROUND (synchronous) so the Biometric
    Device form can show live progress (via realtime events) and then display
    the final results immediately, without needing to check Attendance Sync
    Log separately.

    Realtime progress events are published on "zkteco_pull_progress" while
    this runs. The final return value also contains the full result summary.
    """
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    device = frappe.get_doc("Biometric Device", device_name)
    if device.status != "Active":
        frappe.throw(_("Device {0} is not Active. Please activate it first.").format(device_name))

    from zkteco_attendance.zkteco_attendance.sync_engine import sync_device

    result = sync_device(device_name, triggered_by="Manual", user=frappe.session.user)
    return result


@frappe.whitelist()
def sync_device(device_name):
    """
    Trigger a background sync for a single device (legacy/queue-based path,
    kept for scripts and the scheduler). For interactive use from the
    Biometric Device form, prefer `pull_checkins_now`, which runs in the
    foreground and reports live progress.
    Result is visible in Attendance Sync Log.
    """
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    device = frappe.get_doc("Biometric Device", device_name)
    if device.status != "Active":
        frappe.throw(_("Device {0} is not Active. Please activate it first.").format(device_name))

    frappe.enqueue(
        "zkteco_attendance.zkteco_attendance.sync_engine.sync_device",
        device_name=device_name,
        triggered_by="Manual",
        queue="long",
        timeout=300,
        job_name="zkteco_sync_{}".format(device_name),
    )

    return {
        "status": "queued",
        "message": _("Sync job queued for device {0}. Check Attendance Sync Log for results.").format(device_name),
    }


@frappe.whitelist()
def sync_all_devices():
    """Trigger background sync for all active devices."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    frappe.enqueue(
        "zkteco_attendance.zkteco_attendance.sync_engine.sync_all_active_devices",
        triggered_by="Manual",
        queue="long",
        timeout=600,
        job_name="zkteco_sync_all",
    )

    return {
        "status": "queued",
        "message": _("Sync jobs queued for all active devices. Check Attendance Sync Log for results."),
    }


@frappe.whitelist()
def get_device_status(device_name=None):
    """Get status summary for one or all devices."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    filters = {"name": device_name} if device_name else {}
    return frappe.get_all(
        "Biometric Device",
        filters=filters,
        fields=["name", "device_name", "device_ip", "status", "last_sync_time",
                "auto_sync_enabled", "sync_frequency"]
    )


@frappe.whitelist()
def get_sync_logs(device_name=None, limit=20):
    """Retrieve recent sync logs."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    filters = {}
    if device_name:
        filters["device"] = device_name

    fields = [
        "name", "device", "start_time", "end_time",
        "total_records_pulled", "new_records_created",
        "duplicate_records", "failed_records",
        "sync_status", "triggered_by"
    ]

    if has_column("Attendance Sync Log", "overtime_records"):
        fields.append("overtime_records")

    return frappe.get_all(
        "Attendance Sync Log",
        filters=filters,
        fields=fields,
        order_by="start_time desc",
        limit=int(limit),
    )


@frappe.whitelist()
def get_latest_sync_log(device_name):
    """Return the single most recent Attendance Sync Log row for a device."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    logs = get_sync_logs(device_name=device_name, limit=1)
    return logs[0] if logs else None


@frappe.whitelist()
def get_dashboard_data():
    """Aggregate data (including chart series) for the ZKTeco dashboard page."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    total_devices = frappe.db.count("Biometric Device")
    online_devices = frappe.db.count("Biometric Device", {"status": "Active"})
    offline_devices = total_devices - online_devices

    today = nowdate()

    # Use frappe.db.sql for date-function filtering -- frappe.db.count()
    # does not support SQL expressions as filter keys (v14/15/16).
    todays_checkins = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmployee Checkin` WHERE DATE(`time`) = %s",
        (today,)
    )[0][0]

    # Check if Attendance Sync Log table exists before querying
    failed_syncs_today = 0
    if frappe.db.table_exists("Attendance Sync Log"):
        failed_syncs_today = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabAttendance Sync Log` WHERE sync_status = 'Failed' AND DATE(start_time) = %s",
            (today,)
        )[0][0]

    last_sync = None
    if frappe.db.table_exists("Attendance Sync Log"):
        rows = frappe.db.sql(
            """SELECT device, start_time, sync_status
               FROM `tabAttendance Sync Log`
               ORDER BY start_time DESC
               LIMIT 1""",
            as_dict=True
        )
        last_sync = rows[0] if rows else None

    # ── Chart 1: Check-ins per day for the last 7 days ──────────────────────
    checkins_chart = _checkins_last_n_days(7)

    # ── Chart 2: Sync results per day for the last 7 days ───────────────────
    sync_chart = _sync_results_last_n_days(7)

    # ── Chart 3: Device status breakdown (pie/donut) ────────────────────────
    device_status_chart = {
        "labels": [_("Online"), _("Offline")],
        "values": [online_devices, offline_devices],
    }

    # ── Chart 4: Today's IN vs OUT vs Overtime checkins ─────────────────────
    punch_breakdown_chart = _todays_punch_breakdown(today)

    return {
        "total_devices": total_devices,
        "online_devices": online_devices,
        "offline_devices": offline_devices,
        "todays_checkins": todays_checkins,
        "failed_syncs_today": failed_syncs_today,
        "last_sync": last_sync,
        "charts": {
            "checkins_last_7_days": checkins_chart,
            "sync_results_last_7_days": sync_chart,
            "device_status": device_status_chart,
            "todays_punch_breakdown": punch_breakdown_chart,
        },
    }


def _checkins_last_n_days(n=7):
    """Daily Employee Checkin counts for the last n days (line/bar chart)."""
    start_date = add_days(nowdate(), -(n - 1))

    rows = frappe.db.sql(
        """SELECT DATE(`time`) as day, COUNT(*) as cnt
           FROM `tabEmployee Checkin`
           WHERE DATE(`time`) BETWEEN %s AND %s
           GROUP BY DATE(`time`)
           ORDER BY day ASC""",
        (start_date, nowdate()),
        as_dict=True,
    )
    counts_by_day = {str(r["day"]): r["cnt"] for r in rows}

    labels = []
    values = []
    for i in range(n):
        d = add_days(start_date, i)
        labels.append(frappe.utils.formatdate(d, "dd MMM"))
        values.append(counts_by_day.get(str(d), 0))

    return {"labels": labels, "values": values}


def _sync_results_last_n_days(n=7):
    """Daily sync record counts (new/duplicate/failed) for the last n days."""
    if not frappe.db.table_exists("Attendance Sync Log"):
        return {"labels": [], "new": [], "duplicate": [], "failed": []}

    start_date = add_days(nowdate(), -(n - 1))

    rows = frappe.db.sql(
        """SELECT DATE(start_time) as day,
                  SUM(new_records_created) as new_records,
                  SUM(duplicate_records) as dupes,
                  SUM(failed_records) as failed
           FROM `tabAttendance Sync Log`
           WHERE DATE(start_time) BETWEEN %s AND %s
           GROUP BY DATE(start_time)
           ORDER BY day ASC""",
        (start_date, nowdate()),
        as_dict=True,
    )
    by_day = {str(r["day"]): r for r in rows}

    labels, new_vals, dupe_vals, failed_vals = [], [], [], []
    for i in range(n):
        d = add_days(start_date, i)
        key = str(d)
        labels.append(frappe.utils.formatdate(d, "dd MMM"))
        row = by_day.get(key)
        new_vals.append(cint(row["new_records"]) if row else 0)
        dupe_vals.append(cint(row["dupes"]) if row else 0)
        failed_vals.append(cint(row["failed"]) if row else 0)

    return {"labels": labels, "new": new_vals, "duplicate": dupe_vals, "failed": failed_vals}


def _todays_punch_breakdown(today):
    """Count of IN / OUT / Overtime Employee Checkins created today."""
    has_overtime_col = has_column("Employee Checkin", "is_overtime")

    in_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmployee Checkin` WHERE DATE(`time`) = %s AND log_type = 'IN'",
        (today,)
    )[0][0]
    out_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabEmployee Checkin` WHERE DATE(`time`) = %s AND log_type = 'OUT'",
        (today,)
    )[0][0]

    overtime_count = 0
    if has_overtime_col:
        overtime_count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabEmployee Checkin` WHERE DATE(`time`) = %s AND is_overtime = 1",
            (today,)
        )[0][0]

    return {
        "labels": [_("IN"), _("OUT"), _("Overtime")],
        "values": [cint(in_count), cint(out_count), cint(overtime_count)],
    }
