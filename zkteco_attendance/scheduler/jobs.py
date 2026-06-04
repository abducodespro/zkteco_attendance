"""
Scheduler job entry points for ZKTeco Attendance.

These functions are registered in hooks.py under scheduler_events
and are called by the Frappe background scheduler.
"""
import frappe
import logging

logger = logging.getLogger(__name__)


def sync_5min_devices():
    """Sync devices configured for 5-minute intervals."""
    _run_for_frequency("5 Min")


def sync_15min_devices():
    """Sync devices configured for 15-minute intervals."""
    _run_for_frequency("15 Min")


def sync_30min_devices():
    """Sync devices configured for 30-minute intervals."""
    _run_for_frequency("30 Min")


def sync_hourly_devices():
    """Sync devices configured for hourly intervals."""
    _run_for_frequency("Hourly")


def sync_daily_devices():
    """Sync devices configured for daily intervals."""
    _run_for_frequency("Daily")


def cleanup_old_logs():
    """
    Delete Attendance Sync Logs older than 90 days.
    Runs daily to prevent unbounded log growth.
    """
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-90)
    old_logs = frappe.get_all(
        "Attendance Sync Log",
        filters={"creation": ["<", cutoff]},
        pluck="name",
    )

    if not old_logs:
        return

    for log_name in old_logs:
        frappe.delete_doc("Attendance Sync Log", log_name, ignore_permissions=True)

    frappe.db.commit()
    logger.info(f"ZKTeco: Cleaned up {len(old_logs)} old sync logs")


# ─────────────────────────────────────────
#  Internal
# ─────────────────────────────────────────

def _run_for_frequency(frequency: str):
    """
    Dispatch sync jobs for all active devices matching the given frequency.
    Wraps the sync engine to catch top-level scheduler errors.
    """
    try:
        from zkteco_attendance.utils.sync_engine import (
            run_sync_for_frequency,
        )
        run_sync_for_frequency(frequency)
    except Exception as e:
        logger.error(
            f"ZKTeco Scheduler: Error dispatching '{frequency}' sync jobs: {e}"
        )
        frappe.log_error(
            title=f"ZKTeco Scheduler Error ({frequency})",
            message=str(e),
        )
