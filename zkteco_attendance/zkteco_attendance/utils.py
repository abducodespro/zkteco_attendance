"""
Shared small utilities for ZKTeco Attendance.
Kept dependency-free so it can be imported from anywhere
(attendance_processor, sync_engine, api.endpoints) without
circular-import risk.
"""

import frappe


def has_column(doctype, column):
    """
    Portable column-existence check across Frappe v14/v15/v16.

    `frappe.db.has_column` exists on recent versions but to stay safe on
    older v14 builds we fall back to `get_table_columns`, which has been
    stable for a very long time.
    """
    try:
        if hasattr(frappe.db, "has_column"):
            return bool(frappe.db.has_column(doctype, column))
    except Exception:
        pass

    try:
        columns = frappe.db.get_table_columns(doctype)
        return column in columns
    except Exception:
        return False
