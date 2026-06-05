# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
import logging

logger = logging.getLogger(__name__)


def sync_5min_devices():
    _run_for_frequency("5 Min")

def sync_15min_devices():
    _run_for_frequency("15 Min")

def sync_30min_devices():
    _run_for_frequency("30 Min")

def sync_hourly_devices():
    _run_for_frequency("Hourly")

def sync_daily_devices():
    _run_for_frequency("Daily")

def cleanup_old_logs():
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-90)
    old_logs = frappe.get_all("Attendance Sync Log",
        filters={"creation": ["<", cutoff]}, pluck="name")
    for name in old_logs:
        frappe.delete_doc("Attendance Sync Log", name, ignore_permissions=True)
    frappe.db.commit()

def _run_for_frequency(frequency):
    try:
        from zkteco_attendance.utils.sync_engine import run_sync_for_frequency
        run_sync_for_frequency(frequency)
    except Exception as e:
        logger.error(f"ZKTeco Scheduler error ({frequency}): {e}")
        frappe.log_error(title=f"ZKTeco Scheduler Error ({frequency})", message=str(e))
