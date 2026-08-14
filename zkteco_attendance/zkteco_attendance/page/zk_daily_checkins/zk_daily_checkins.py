import frappe


@frappe.whitelist()
def get_data(attendance_summary=None, from_date=None, to_date=None,
             employee_list=None, company=None):
    from zkteco_attendance.zkteco_attendance.api.endpoints import get_daily_checkins
    return get_daily_checkins(
        attendance_summary=attendance_summary,
        from_date=from_date,
        to_date=to_date,
        employee_list=employee_list,
        company=company,
    )


@frappe.whitelist()
def save_manual_checkin(attendance_summary, employee, checkin_time, log_type,
                        checkin_name=None):
    from zkteco_attendance.zkteco_attendance.api.endpoints import save_manual_checkin as _save
    return _save(attendance_summary=attendance_summary, employee=employee,
                 checkin_time=checkin_time, log_type=log_type, checkin_name=checkin_name)
