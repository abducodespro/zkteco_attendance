"""
Patch v1_4 — Add all v2 custom fields and doctype changes:
- Employee: zk_biometric_device (Link -> Biometric Device)
- Employee Checkin: manually_edited, edited_by, edited_at
- Attendance Sync Log: double_punch_records
- ZK Shift Type: Saturday + OT window fields (via doctype sync)
- Attendance Summary Detail: day_ot_hours, night_ot_hours (via doctype sync)
"""
import frappe


def execute():
    from zkteco_attendance.zkteco_attendance.install import (
        _add_employee_location_device_field,
        _add_employee_checkin_manual_fields,
        _add_employee_biometric_field,
        _add_employee_checkin_device_field,
        _add_employee_checkin_zk_uid_field,
        _add_employee_checkin_overtime_field,
    )

    _add_employee_biometric_field()
    _add_employee_checkin_device_field()
    _add_employee_checkin_zk_uid_field()
    _add_employee_checkin_overtime_field()
    _add_employee_location_device_field()
    _add_employee_checkin_manual_fields()

    # Reload doctypes so new columns get created in DB
    for module, doctype in [
        ("zkteco_attendance", "zk_shift_type"),
        ("zkteco_attendance", "attendance_summary_detail"),
        ("zkteco_attendance", "attendance_sync_log"),
        ("zkteco_attendance", "zk_daily_checkins"),
    ]:
        try:
            frappe.reload_doc(module, "doctype", doctype)
        except Exception:
            try:
                frappe.reload_doc(module, "page", doctype)
            except Exception:
                pass

    frappe.db.commit()
