"""
Installation hooks for ZKTeco Attendance app.
"""
import frappe
from frappe import _


def after_install():
    """Run after app installation."""
    frappe.logger().info("ZKTeco Attendance: Running after_install hooks")
    _create_custom_roles()
    # Note: role permissions and workspace are handled by DocType JSON
    # fixtures and bench migrate — no need to create them here.
    frappe.logger().info("ZKTeco Attendance: Installation complete")


def after_migrate():
    """Run after every bench migrate."""
    frappe.logger().info("ZKTeco Attendance: Running after_migrate hooks")


def _create_custom_roles():
    """Create roles needed for the app."""
    roles = ["Attendance Manager"]
    for role in roles:
        if not frappe.db.exists("Role", role):
            doc = frappe.new_doc("Role")
            doc.role_name = role
            doc.desk_access = 1
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.logger().info(f"ZKTeco Attendance: Created role '{role}'")
