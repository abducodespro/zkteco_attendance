"""
Patch: v1_3 — Add "Employee Daily Checkins" dashboard page and link it from
the Biometric Attendance workspace + Attendance Summary, for sites that
installed this app before this feature existed.
"""

import frappe


def execute():
    try:
        frappe.reload_doc("zkteco_attendance", "page", "zk_daily_checkins")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload Page 'zk-daily-checkins'",
            title="ZKTeco Patch v1_3"
        )

    try:
        frappe.reload_doc("zkteco_attendance", "workspace", "biometric_attendance")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload Workspace 'Biometric Attendance'",
            title="ZKTeco Patch v1_3"
        )

    frappe.db.commit()
