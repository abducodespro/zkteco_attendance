"""
Patch: v1_1 — Overtime management + checkin metadata fields.

Adds, for sites that already had ZKTeco Attendance installed before
overtime management / progress-tracking support was introduced:

- Employee Checkin: zk_uid, is_overtime custom fields
- Attendance Summary Detail: overtime_hours, overtime_amount
- ZK Shift Type: overtime configuration fields (run via doctype sync,
  this patch just ensures defaults are set on existing rows)
"""

import frappe


def execute():
    from zkteco_attendance.zkteco_attendance.install import (
        _add_employee_checkin_zk_uid_field,
        _add_employee_checkin_overtime_field,
    )

    _add_employee_checkin_zk_uid_field()
    _add_employee_checkin_overtime_field()

    # Ensure existing ZK Shift Type rows get sensible overtime defaults
    # (wrapped in try/except: doctype sync may not have added the new
    # columns yet depending on patch/sync order across v14/v15/v16)
    if frappe.db.table_exists("ZK Shift Type"):
        try:
            frappe.db.sql("""
                UPDATE `tabZK Shift Type`
                SET enable_overtime = 0,
                    overtime_calculation_method = 'After Standard Hours'
                WHERE enable_overtime IS NULL
            """)
        except Exception:
            frappe.db.rollback()

    frappe.db.commit()
