"""
Install / Uninstall hooks for ZKTeco Attendance.
"""

import frappe
from frappe import _


def after_install():
    """Run after app is installed via bench install-app."""
    _create_biometric_device_manager_role()
    _add_employee_biometric_field()
    _add_employee_checkin_device_field()
    frappe.db.commit()
    frappe.msgprint(_("ZKTeco Attendance installed successfully."))


def before_uninstall():
    """Cleanup on uninstall."""
    pass


def _create_biometric_device_manager_role():
    if not frappe.db.exists("Role", "Biometric Device Manager"):
        role = frappe.get_doc({
            "doctype": "Role",
            "role_name": "Biometric Device Manager",
            "desk_access": 1,
            "is_custom": 1,
        })
        role.insert(ignore_permissions=True)


def _add_employee_biometric_field():
    """Add attendance_device_id custom field to Employee if it doesn't exist."""
    if frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "attendance_device_id"}):
        return

    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Employee",
        "module": "Zkteco Attendance",
        "label": "Biometric Attendance ID",
        "fieldname": "attendance_device_id",
        "fieldtype": "Data",
        "insert_after": "attendance_device_id",
        "description": "ID enrolled on the ZKTeco biometric device. Used to match attendance records.",
        "in_list_view": 0,
        "search_index": 1,
    })
    cf.insert(ignore_permissions=True)


def _add_employee_checkin_device_field():
    """Add device_id field to Employee Checkin if not already there."""
    if frappe.db.exists("Custom Field", {"dt": "Employee Checkin", "fieldname": "device_id"}):
        return

    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Employee Checkin",
        "module": "Zkteco Attendance",
        "label": "Biometric Device",
        "fieldname": "device_id",
        "fieldtype": "Data",
        "insert_after": "log_type",
        "description": "ZKTeco device that recorded this checkin.",
        "in_list_view": 0,
    })
    cf.insert(ignore_permissions=True)
