import frappe


@frappe.whitelist()
def get_data(attendance_summary):
    from zkteco_attendance.zkteco_attendance.api.endpoints import get_daily_checkins
    return get_daily_checkins(attendance_summary)
