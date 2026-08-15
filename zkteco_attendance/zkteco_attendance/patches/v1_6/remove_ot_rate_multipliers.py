"""
Patch: v1_6 — Remove OT rate multiplier fields from ZK Shift Type.

Removes the now-unused fields for existing installs:
- overtime_rate_multiplier
- day_overtime_rate
- night_overtime_rate

The doctype is re-synced from JSON and any leftover DB columns are
dropped explicitly (older Frappe versions do not always drop columns
that were removed from the doctype definition).
"""

import frappe
from zkteco_attendance.zkteco_attendance.utils import has_column

RATE_FIELDS = ("overtime_rate_multiplier", "day_overtime_rate", "night_overtime_rate")


def execute():
    try:
        frappe.reload_doc("zkteco_attendance", "doctype", "zk_shift_type")
    except Exception:
        frappe.log_error(
            message="ZKTeco: could not reload DocType 'ZK Shift Type' to remove OT rate multipliers",
            title="ZKTeco Patch v1_6"
        )

    if frappe.db.table_exists("ZK Shift Type"):
        for fieldname in RATE_FIELDS:
            if has_column("ZK Shift Type", fieldname):
                try:
                    frappe.db.sql(
                        "ALTER TABLE `tabZK Shift Type` DROP COLUMN `{0}`".format(fieldname)
                    )
                except Exception:
                    frappe.db.rollback()

    frappe.db.commit()
