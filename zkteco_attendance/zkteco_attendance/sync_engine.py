"""
Sync Engine
Orchestrates pulling from devices, mapping employees, creating
Employee Checkin records, and logging results to Attendance Sync Log.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime
from datetime import timedelta

from .zk_client import pull_attendance_from_device, get_punch_type


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


def checkin_exists(employee, timestamp, log_type, device_name):
    """
    Duplicate check: return True if a matching checkin already exists
    within a ±60 second window.
    Uses raw SQL for v14 compatibility (no SQL-expression filter keys).
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


def create_employee_checkin(employee, employee_name, timestamp, log_type, device_name):
    """Create a single Employee Checkin record."""
    doc = frappe.get_doc({
        "doctype": "Employee Checkin",
        "employee": employee,
        "employee_name": employee_name,
        "time": timestamp,
        "log_type": log_type,
        "device_id": device_name,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def sync_device(device_name, triggered_by="Manual"):
    """
    Full sync for a single device:
    1. Pull records from device
    2. Map to ERPNext employees
    3. Create Employee Checkin records
    4. Log result to Attendance Sync Log
    5. Update last_sync_time on the device
    """
    device = frappe.get_doc("Biometric Device", device_name)

    if device.status != "Active":
        return {"success": False, "error": "Device is not Active"}

    sync_start = now_datetime()
    total_records = 0
    new_records   = 0
    duplicates    = 0
    failed        = 0
    errors        = []

    try:
        records = pull_attendance_from_device(device, fetch_mode=device.fetch_mode or "All Records")
        total_records = len(records)
    except Exception as e:
        _save_sync_log(
            device=device_name,
            start_time=sync_start,
            end_time=now_datetime(),
            total=0, created=0, dupes=0, failed=0,
            status="Failed",
            error=str(e),
            triggered_by=triggered_by,
        )
        frappe.db.set_value("Biometric Device", device_name, "status", "Inactive")
        frappe.db.commit()
        return {"success": False, "error": str(e)}

    for rec in records:
        try:
            user_id   = str(rec["user_id"])
            timestamp = rec["timestamp"]
            log_type  = get_punch_type(rec["punch"])

            emp = get_employee_by_biometric_id(user_id, company=device.company)
            if not emp:
                failed += 1
                errors.append("No employee found for biometric ID: {}".format(user_id))
                continue

            if checkin_exists(emp["name"], timestamp, log_type, device_name):
                duplicates += 1
                continue

            create_employee_checkin(
                emp["name"], emp["employee_name"], timestamp, log_type, device_name
            )
            new_records += 1

        except Exception as e:
            failed += 1
            errors.append("uid={}: {}".format(rec.get("uid"), str(e)))
            frappe.log_error(
                message="Failed checkin for device {}, uid {}: {}".format(
                    device_name, rec.get("uid"), str(e)
                ),
                title="ZKTeco Checkin Error"
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
        status=sync_status,
        error="\n".join(errors[:50]) if errors else "",
        triggered_by=triggered_by,
    )

    frappe.db.set_value("Biometric Device", device_name, {
        "last_sync_time": sync_end,
        "status": "Active",
    })
    frappe.db.commit()

    return {
        "success": True,
        "total_records": total_records,
        "new_records":   new_records,
        "duplicates":    duplicates,
        "failed":        failed,
        "sync_status":   sync_status,
    }


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
                   dupes, failed, status, error, triggered_by):
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
