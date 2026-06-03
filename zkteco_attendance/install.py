"""
Installation hooks for ZKTeco Attendance app.
"""
import frappe
from frappe import _


def after_install():
    """Run after app installation."""
    frappe.logger().info("ZKTeco Attendance: Running after_install hooks")
    _create_custom_roles()
    _create_role_permissions()
    _create_workspace()
    frappe.logger().info("ZKTeco Attendance: Installation complete")


def after_migrate():
    """Run after every bench migrate."""
    frappe.logger().info("ZKTeco Attendance: Running after_migrate hooks")
    _create_role_permissions()


def _create_custom_roles():
    """Create roles needed for the app."""
    roles = ["Attendance Manager"]
    for role in roles:
        if not frappe.db.exists("Role", role):
            doc = frappe.new_doc("Role")
            doc.role_name = role
            doc.desk_access = 1
            doc.insert(ignore_permissions=True)
            frappe.logger().info(f"ZKTeco Attendance: Created role '{role}'")


def _create_role_permissions():
    """Set up default role permissions for all DocTypes."""
    doctype_perms = {
        "Biometric Device": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "HR Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Attendance Manager", "read": 1, "write": 1, "create": 1},
        ],
        "Attendance Sync Log": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "HR Manager", "read": 1},
            {"role": "Attendance Manager", "read": 1},
        ],
        "Device Employee Mapping": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "HR Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Attendance Manager", "read": 1, "write": 1, "create": 1},
        ],
    }

    for doctype, perms in doctype_perms.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        # Clear existing and recreate
        frappe.db.delete("DocPerm", {"parent": doctype})
        for perm in perms:
            dp = frappe.new_doc("DocPerm")
            dp.parent = doctype
            dp.parenttype = "DocType"
            dp.parentfield = "permissions"
            dp.update(perm)
            dp.insert(ignore_permissions=True)

    frappe.db.commit()


def _create_workspace():
    """Create the ZKTeco workspace in Frappe desk."""
    if frappe.db.exists("Workspace", "ZKTeco Attendance"):
        return

    ws = frappe.new_doc("Workspace")
    ws.name = "ZKTeco Attendance"
    ws.label = "ZKTeco Attendance"
    ws.category = "Modules"
    ws.module = "ZKTeco Attendance"
    ws.icon = "users"
    ws.is_standard = 0
    ws.content = "[]"
    ws.insert(ignore_permissions=True)
    frappe.logger().info("ZKTeco Attendance: Workspace created")
