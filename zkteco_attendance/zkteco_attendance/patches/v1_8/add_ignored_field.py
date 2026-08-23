"""
Patch: v1_8 — Add zk_ignored field to Employee Checkin.

Adds a checkbox so checkins can be excluded from attendance processing
from the Employee Daily Checkins page.
"""

import frappe


def execute():
    try:
        frappe.reload_doc("zkteco_attendance", "doctype", "biometric_device")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload DocType for v1_8 patch",
            title="ZKTeco Patch v1_8"
        )

    frappe.db.commit()
