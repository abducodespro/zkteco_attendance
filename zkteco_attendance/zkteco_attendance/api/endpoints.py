"""
Whitelisted API endpoints for ZKTeco Attendance.
These are callable from JavaScript / REST.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, nowdate


@frappe.whitelist()
def test_connection(device_name):
    """Test connection to a biometric device and return device info."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])
    from zkteco_attendance.zkteco_attendance.zk_client import test_device_connection
    return test_device_connection(device_name)


@frappe.whitelist()
def sync_device(device_name):
    """
    Trigger an immediate (background) sync for a single device.
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

    return frappe.get_all(
        "Attendance Sync Log",
        filters=filters,
        fields=[
            "name", "device", "start_time", "end_time",
            "total_records_pulled", "new_records_created",
            "duplicate_records", "failed_records",
            "sync_status", "triggered_by"
        ],
        order_by="start_time desc",
        limit=int(limit),
    )


@frappe.whitelist()
def get_dashboard_data():
    """Aggregate data for the ZKTeco dashboard page."""
    frappe.only_for(["System Manager", "HR Manager", "Biometric Device Manager"])

    total_devices = frappe.db.count("Biometric Device")
    online_devices = frappe.db.count("Biometric Device", {"status": "Active"})
    offline_devices = total_devices - online_devices

    today = nowdate()

    # Use frappe.db.sql for date-function filtering — frappe.db.count()
    # does not support SQL expressions as filter keys (v14 limitation).
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

    return {
        "total_devices": total_devices,
        "online_devices": online_devices,
        "offline_devices": offline_devices,
        "todays_checkins": todays_checkins,
        "failed_syncs_today": failed_syncs_today,
        "last_sync": last_sync,
    }
