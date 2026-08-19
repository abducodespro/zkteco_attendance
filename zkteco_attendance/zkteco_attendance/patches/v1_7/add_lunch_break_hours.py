"""
Patch: v1_7 — Add lunch_break_hours field to ZK Shift Type.

Adds the new Float column so existing installs can store the lunch
break duration.  Default is 0 (no deduction), preserving current
behaviour for all shifts.
"""

import frappe


def execute():
    try:
        frappe.reload_doc("zkteco_attendance", "doctype", "zk_shift_type")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload DocType 'ZK Shift Type' for lunch_break_hours",
            title="ZKTeco Patch v1_7"
        )

    frappe.db.commit()
