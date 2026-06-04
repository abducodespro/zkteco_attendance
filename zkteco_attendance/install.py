import frappe

def after_install():
    frappe.logger().info("ZKTeco Attendance: Running after_install hooks")
    _create_module_def()
    _create_custom_roles()
    frappe.db.commit()
    frappe.logger().info("ZKTeco Attendance: Installation complete")

def after_migrate():
    frappe.logger().info("ZKTeco Attendance: Running after_migrate hooks")

def _create_module_def():
    if frappe.db.exists("Module Def", "ZKTeco Attendance"):
        return
    module_def = frappe.new_doc("Module Def")
    module_def.module_name = "ZKTeco Attendance"
    module_def.app_name = "zkteco_attendance"
    module_def.insert(ignore_permissions=True)
    frappe.logger().info("ZKTeco Attendance: Module Def created")

def _create_custom_roles():
    roles = ["Attendance Manager"]
    for role in roles:
        if not frappe.db.exists("Role", role):
            doc = frappe.new_doc("Role")
            doc.role_name = role
            doc.desk_access = 1
            doc.insert(ignore_permissions=True)
