"""
Patch: v1_2 — Add "Check-ins (Last 7 Days)" dashboard chart to the
Biometric Attendance workspace for sites that installed this app before
the chart existed.
"""

import json
import frappe


def execute():
    # Ensure the standard Dashboard Chart record (module-bundled JSON) is
    # synced to the database.
    try:
        frappe.reload_doc("zkteco_attendance", "dashboard_chart", "checkins_last_7_days")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload Dashboard Chart 'Check-ins (Last 7 Days)'",
            title="ZKTeco Patch v1_2"
        )

    # Re-sync the workspace so the new chart block appears for existing sites.
    try:
        frappe.reload_doc("zkteco_attendance", "workspace", "biometric_attendance")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload Workspace 'Biometric Attendance'",
            title="ZKTeco Patch v1_2"
        )

    frappe.db.commit()
