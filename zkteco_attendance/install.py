# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe


def after_install():
    frappe.logger().info("ZKTeco Attendance: after_install started")
    _create_module_def()
    _create_custom_roles()
    frappe.db.commit()
    frappe.logger().info("ZKTeco Attendance: after_install complete")


def after_migrate():
    frappe.logger().info("ZKTeco Attendance: after_migrate")


def _create_module_def():
    if frappe.db.exists("Module Def", "ZKTeco Attendance"):
        return
    doc = frappe.new_doc("Module Def")
    doc.module_name = "ZKTeco Attendance"
    doc.app_name = "zkteco_attendance"
    doc.insert(ignore_permissions=True)
    frappe.logger().info("ZKTeco Attendance: Module Def created")


def _create_custom_roles():
    for role in ["Attendance Manager"]:
        if not frappe.db.exists("Role", role):
            doc = frappe.new_doc("Role")
            doc.role_name = role
            doc.desk_access = 1
            doc.insert(ignore_permissions=True)
            frappe.logger().info(f"ZKTeco Attendance: Role '{role}' created")
