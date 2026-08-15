"""
Patch: v1_5 — Add explicit Day / Night / Weekend / Holiday overtime fields.

Adds, for sites that already had ZKTeco Attendance installed before the
four-category overtime breakdown was introduced:

- Attendance Summary Detail: weekend_ot_hours, holiday_ot_hours
- Attendance Summary: total_day_ot_hours, total_night_ot_hours,
  total_weekend_ot_hours, total_holiday_ot_hours
  (day_ot_hours / night_ot_hours already existed via v1_4)

The columns are created by re-syncing the doctype JSON from disk.
"""

import frappe


def execute():
    for doctype in ("attendance_summary", "attendance_summary_detail"):
        try:
            frappe.reload_doc("zkteco_attendance", "doctype", doctype)
        except Exception:
            frappe.log_error(
                message="ZKTeco: could not reload DocType '{}' for OT category fields".format(doctype),
                title="ZKTeco Patch v1_5"
            )

    frappe.db.commit()
