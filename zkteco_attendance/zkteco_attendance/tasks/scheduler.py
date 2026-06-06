"""
Scheduler tasks for Frappe v14.

Frappe v14 does NOT support the "cron" key in scheduler_events.
Instead we use "all" (fires roughly every minute via `bench schedule`)
and check the last-sync time ourselves to honour each device's
configured sync_frequency.
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds
from zkteco_attendance.zkteco_attendance.sync_engine import sync_all_active_devices

# Minimum elapsed seconds before we re-sync, keyed by sync_frequency label
FREQUENCY_SECONDS = {
    "5 Min":  5  * 60,
    "15 Min": 15 * 60,
    "30 Min": 30 * 60,
    "Hourly": 60 * 60,
    "Daily":  24 * 60 * 60,
}


def sync_devices_on_schedule():
    """
    Called every minute by the Frappe scheduler ("all" event).
    Checks each active device's sync_frequency and last_sync_time
    to decide whether it is due for a sync.
    """
    try:
        devices = frappe.get_all(
            "Biometric Device",
            filters={"status": "Active", "auto_sync_enabled": 1},
            fields=["name", "sync_frequency", "last_sync_time"],
        )

        now = now_datetime()

        for device in devices:
            freq = device.get("sync_frequency") or "30 Min"
            min_gap = FREQUENCY_SECONDS.get(freq, 30 * 60)

            # Skip if synced recently enough
            last = device.get("last_sync_time")
            if last:
                elapsed = time_diff_in_seconds(now, last)
                if elapsed < min_gap:
                    continue

            # Skip "Hourly" and "Daily" — handled by their own scheduler hooks
            if freq in ("Hourly", "Daily"):
                continue

            try:
                from zkteco_attendance.zkteco_attendance.sync_engine import sync_device
                sync_device(device["name"], triggered_by="Scheduler")
            except Exception as e:
                frappe.log_error(
                    message="ZKTeco scheduler failed for device {}: {}".format(device["name"], str(e)),
                    title="ZKTeco Scheduler Error"
                )

    except Exception as e:
        frappe.log_error(message=str(e), title="ZKTeco Scheduler (all) Error")


def sync_devices_hourly():
    """Called once per hour by the Frappe scheduler."""
    try:
        sync_all_active_devices(frequency_filter="Hourly", triggered_by="Scheduler")
    except Exception as e:
        frappe.log_error(message=str(e), title="ZKTeco Scheduler Hourly Error")


def sync_devices_daily():
    """Called once per day by the Frappe scheduler."""
    try:
        sync_all_active_devices(frequency_filter="Daily", triggered_by="Scheduler")
    except Exception as e:
        frappe.log_error(message=str(e), title="ZKTeco Scheduler Daily Error")


# --- Legacy stubs (kept so old hooks references don't crash) ---
def sync_devices_5min():
    sync_devices_on_schedule()

def sync_devices_15min():
    sync_devices_on_schedule()

def sync_devices_30min():
    sync_devices_on_schedule()
