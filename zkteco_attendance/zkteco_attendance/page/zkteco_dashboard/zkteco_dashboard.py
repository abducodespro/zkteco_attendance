import frappe

@frappe.whitelist()
def get_data():
    from zkteco_attendance.zkteco_attendance.api.endpoints import get_dashboard_data
    return get_dashboard_data()
