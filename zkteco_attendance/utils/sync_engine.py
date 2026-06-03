"""
Sync Engine: Orchestrates the full attendance sync workflow.

Flow:
  1. Connect to ZKTeco device
  2. Fetch attendance records (all or since last sync)
  3. For each record, resolve Device User ID → ERPNext Employee
  4. Convert timestamps with timezone handling
  5. Create Employee Checkin records (skip duplicates)
  6. Optionally clear device logs
  7. Write Attendance Sync Log
  8. Update device's Last Sync Time
"""
import frappe
from frappe import _
from frappe.utils import (
    now_datetime,
    get_datetime,
    convert_utc_to_user_timezone,
)
import traceback
import logging
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)


def run_sync_for_device(device_name: str, triggered_by: str = "Scheduler"):
    """
    Entry point for background job: sync a single device.

    Args:
        device_name: Name of the Biometric Device document
        triggered_by: "Manual" or "Scheduler"
    """
    logger.info(f"SyncEngine: Starting sync for device '{device_name}' (triggered by {triggered_by})")

    # Create audit log
    sync_log = frappe.new_doc("Attendance Sync Log")
    sync_log.device = device_name
    sync_log.triggered_by = triggered_by
    sync_log.sync_status = "In Progress"
    sync_log.start_time = now_datetime()
    sync_log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        device = frappe.get_doc("Biometric Device", device_name)

        if device.status != "Active":
            sync_log.mark_failed(f"Device '{device_name}' is not Active")
            return

        engine = AttendanceSyncEngine(device, sync_log)
        engine.execute()

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.error(f"SyncEngine: Fatal error for device '{device_name}': {e}\n{error_detail}")

        try:
            sync_log.reload()
            sync_log.mark_failed(f"{str(e)}\n\n{error_detail}")
        except Exception:
            pass


def run_sync_for_frequency(frequency: str):
    """
    Sync all active devices matching the given frequency.

    Args:
        frequency: One of "5 Min", "15 Min", "30 Min", "Hourly", "Daily"
    """
    devices = frappe.get_all(
        "Biometric Device",
        filters={
            "status": "Active",
            "auto_sync_enabled": 1,
            "sync_frequency": frequency,
        },
        pluck="name",
    )

    logger.info(f"SyncEngine: Found {len(devices)} device(s) for frequency '{frequency}'")

    for device_name in devices:
        try:
            frappe.enqueue(
                "zkteco_attendance.zkteco_attendance.utils.sync_engine.run_sync_for_device",
                device_name=device_name,
                triggered_by="Scheduler",
                queue="long",
                timeout=600,
                is_async=True,
                job_name=f"zk_auto_{device_name}",
            )
        except Exception as e:
            logger.error(f"SyncEngine: Failed to enqueue sync for '{device_name}': {e}")


class AttendanceSyncEngine:
    """
    Core sync logic for a single device.
    """

    def __init__(self, device_doc, sync_log_doc):
        self.device = device_doc
        self.sync_log = sync_log_doc
        self.tz = self._get_timezone()
        self._employee_cache = {}  # {device_user_id: employee_id}
        self._checkin_cache = set()  # {(employee, timestamp_str)} for dup detection

    # ─────────────────────────────────────────
    #  Public
    # ─────────────────────────────────────────

    def execute(self):
        """Run the full sync workflow."""
        from zkteco_attendance.zkteco_attendance.utils.zk_connector import ZKConnector

        connector = ZKConnector(self.device)
        try:
            since = self._get_since_datetime()
            raw_records = connector.get_attendance_records(since_datetime=since)

            total = len(raw_records)
            created = 0
            duplicates = 0
            failed = 0
            errors = []

            logger.info(
                f"SyncEngine: Processing {total} records for '{self.device.name}'"
            )

            # Pre-load employee mappings for this device
            self._load_employee_mappings()
            # Pre-load existing checkin cache to detect duplicates
            self._load_existing_checkins()

            for record in raw_records:
                try:
                    result = self._process_record(record)
                    if result == "created":
                        created += 1
                    elif result == "duplicate":
                        duplicates += 1
                    elif result == "skipped":
                        pass  # unmapped user
                except Exception as e:
                    failed += 1
                    errors.append(f"Record {getattr(record, 'user_id', '?')} @ {getattr(record, 'timestamp', '?')}: {e}")
                    logger.warning(f"SyncEngine: Failed to process record: {e}")

            # Optionally clear device logs
            if self.device.clear_device_logs_after_sync and created > 0:
                try:
                    connector.clear_attendance()
                    logger.info(f"SyncEngine: Cleared device logs for '{self.device.name}'")
                except Exception as e:
                    errors.append(f"Clear logs failed: {e}")

        finally:
            connector.disconnect()

        # Update sync log
        self.sync_log.mark_complete(total, created, duplicates, failed, errors if errors else None)

        # Update device's last sync time
        self.device.update_sync_time()

        logger.info(
            f"SyncEngine: Completed '{self.device.name}' — "
            f"total={total}, created={created}, dup={duplicates}, failed={failed}"
        )

    # ─────────────────────────────────────────
    #  Record Processing
    # ─────────────────────────────────────────

    def _process_record(self, record) -> str:
        """
        Process a single attendance record.

        Returns:
            "created"   — new Employee Checkin created
            "duplicate" — record already exists
            "skipped"   — no employee mapping found
        """
        user_id = str(record.user_id)
        employee = self._get_employee_for_user(user_id)

        if not employee:
            logger.debug(
                f"SyncEngine: No mapping for device user '{user_id}' on '{self.device.name}'"
            )
            return "skipped"

        # Convert timestamp to server timezone
        timestamp = self._convert_timestamp(record.timestamp)
        if not timestamp:
            logger.warning(f"SyncEngine: Invalid timestamp for user {user_id}, skipping")
            return "skipped"

        # Determine log type (IN/OUT)
        from zkteco_attendance.zkteco_attendance.utils.zk_connector import ZKConnector
        punch_type = getattr(record, "punch", 0)
        log_type = ZKConnector.punch_type_to_log_type(punch_type)

        # Check duplicate
        cache_key = (employee, timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        if cache_key in self._checkin_cache:
            return "duplicate"

        # Create Employee Checkin
        self._create_checkin(employee, timestamp, log_type, user_id)
        self._checkin_cache.add(cache_key)
        return "created"

    def _create_checkin(self, employee: str, timestamp: datetime, log_type: str, device_user_id: str):
        """
        Create an ERPNext Employee Checkin record.
        """
        checkin = frappe.new_doc("Employee Checkin")
        checkin.employee = employee
        checkin.time = timestamp
        checkin.log_type = log_type
        checkin.device_id = self.device.name
        checkin.skip_auto_attendance = 0
        checkin.insert(ignore_permissions=True)

        logger.debug(
            f"SyncEngine: Created checkin for {employee} @ {timestamp} ({log_type})"
        )

    # ─────────────────────────────────────────
    #  Employee Mapping
    # ─────────────────────────────────────────

    def _load_employee_mappings(self):
        """Load all active mappings for this device into cache."""
        mappings = frappe.get_all(
            "Device Employee Mapping",
            filters={"device": self.device.name, "active": 1},
            fields=["device_user_id", "employee"],
        )
        for m in mappings:
            self._employee_cache[str(m.device_user_id)] = m.employee

        logger.info(
            f"SyncEngine: Loaded {len(self._employee_cache)} employee mappings for '{self.device.name}'"
        )

    def _get_employee_for_user(self, user_id: str):
        """
        Resolve a device user ID to an ERPNext employee.
        Uses in-memory cache; falls back to direct DB lookup.
        """
        if user_id in self._employee_cache:
            return self._employee_cache[user_id]

        # Try direct DB lookup (in case mapping was added mid-sync)
        employee = frappe.db.get_value(
            "Device Employee Mapping",
            {"device": self.device.name, "device_user_id": user_id, "active": 1},
            "employee",
        )
        if employee:
            self._employee_cache[user_id] = employee
        return employee

    # ─────────────────────────────────────────
    #  Duplicate Detection
    # ─────────────────────────────────────────

    def _load_existing_checkins(self):
        """
        Pre-load existing checkins from the DB for the past N days
        into the cache to avoid costly per-record queries.
        """
        since = frappe.utils.add_to_date(now_datetime(), days=-30)
        existing = frappe.db.sql(
            """
            SELECT employee, DATE_FORMAT(time, '%%Y-%%m-%%d %%H:%%i:%%S') as ts
            FROM `tabEmployee Checkin`
            WHERE time >= %s AND device_id = %s
            """,
            (since, self.device.name),
            as_dict=True,
        )
        for row in existing:
            self._checkin_cache.add((row.employee, row.ts))

        logger.info(
            f"SyncEngine: Preloaded {len(self._checkin_cache)} existing checkin keys"
        )

    # ─────────────────────────────────────────
    #  Timestamp & Timezone Handling
    # ─────────────────────────────────────────

    def _get_timezone(self) -> pytz.BaseTzInfo:
        """Get the device timezone object."""
        tz_name = self.device.time_zone or "UTC"
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"SyncEngine: Unknown timezone '{tz_name}', using UTC")
            return pytz.utc

    def _convert_timestamp(self, ts) -> datetime | None:
        """
        Convert a device-local timestamp to server time (UTC or system TZ).

        ZKTeco timestamps are naive datetimes in the device's local timezone.
        We localize them to the configured device timezone, then convert.
        """
        if not ts:
            return None

        try:
            # ts may be a datetime or string
            if isinstance(ts, str):
                ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

            # Make the naive datetime timezone-aware (device TZ)
            if ts.tzinfo is None:
                ts_aware = self.tz.localize(ts)
            else:
                ts_aware = ts.astimezone(self.tz)

            # Convert to UTC for storage
            ts_utc = ts_aware.astimezone(pytz.utc)

            # Return naive UTC for Frappe
            return ts_utc.replace(tzinfo=None)

        except Exception as e:
            logger.warning(f"SyncEngine: Timestamp conversion error: {ts} — {e}")
            return None

    # ─────────────────────────────────────────
    #  Sync Window
    # ─────────────────────────────────────────

    def _get_since_datetime(self):
        """
        Determine the 'fetch since' cutoff for new-records-only mode.
        Returns None for "All Records" mode.
        """
        if self.device.fetch_mode == "All Records":
            return None

        # Use last sync time if available
        if self.device.last_sync_time:
            return get_datetime(self.device.last_sync_time)

        # Default: last 7 days on first sync
        return frappe.utils.add_to_date(now_datetime(), days=-7)
