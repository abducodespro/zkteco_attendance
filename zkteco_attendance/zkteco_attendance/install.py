"""
Install / Uninstall hooks for ZKTeco Attendance.
"""

import frappe
from frappe import _


def after_install():
    """Run after app is installed via bench install-app."""
    _create_biometric_device_manager_role()
    _add_employee_checkin_zk_uid_field()
    _add_employee_checkin_overtime_field()
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

def _add_employee_checkin_zk_uid_field():
    """Add zk_uid field to Employee Checkin (raw device record id, used for de-duplication)."""
    if frappe.db.exists("Custom Field", {"dt": "Employee Checkin", "fieldname": "zk_uid"}):
        return

    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Employee Checkin",
        "module": "Zkteco Attendance",
        "label": "ZK Device Record ID",
        "fieldname": "zk_uid",
        "fieldtype": "Data",
        "insert_after": "device_id",
        "description": "Raw attendance record ID (uid) from the biometric device.",
        "in_list_view": 0,
        "read_only": 1,
        "no_copy": 1,
    })
    cf.insert(ignore_permissions=True)


def _add_employee_checkin_overtime_field():
    """Add is_overtime checkbox to Employee Checkin for overtime punches (OT In/Out)."""
    if frappe.db.exists("Custom Field", {"dt": "Employee Checkin", "fieldname": "is_overtime"}):
        return

    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Employee Checkin",
        "module": "Zkteco Attendance",
        "label": "Overtime Punch",
        "fieldname": "is_overtime",
        "fieldtype": "Check",
        "insert_after": "zk_uid",
        "description": "Set when this checkin was recorded as an Overtime In/Out punch (device punch code 4/5).",
        "in_list_view": 1,
        "no_copy": 1,
    })
    cf.insert(ignore_permissions=True)
