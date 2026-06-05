# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from frappe.utils import now_datetime, get_datetime
import traceback
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


def run_sync_for_device(device_name, triggered_by="Scheduler"):
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
        try:
            sync_log.reload()
            sync_log.mark_failed(f"{str(e)}\n\n{error_detail}")
        except Exception:
            pass


def run_sync_for_frequency(frequency):
    devices = frappe.get_all(
        "Biometric Device",
        filters={"status": "Active", "auto_sync_enabled": 1, "sync_frequency": frequency},
        pluck="name",
    )
    for device_name in devices:
        frappe.enqueue(
            "zkteco_attendance.utils.sync_engine.run_sync_for_device",
            device_name=device_name,
            triggered_by="Scheduler",
            queue="long",
            timeout=600,
            job_name=f"zk_auto_{device_name}",
        )


class AttendanceSyncEngine:

    def __init__(self, device_doc, sync_log_doc):
        self.device = device_doc
        self.sync_log = sync_log_doc
        self.tz = self._get_timezone()
        self._employee_cache = {}
        self._checkin_cache = set()

    def execute(self):
        from zkteco_attendance.utils.zk_connector import ZKConnector
        connector = ZKConnector(self.device)
        total = created = duplicates = failed = 0
        errors = []
        try:
            since = self._get_since_datetime()
            raw_records = connector.get_attendance_records(since_datetime=since)
            total = len(raw_records)
            self._load_employee_mappings()
            self._load_existing_checkins()
            for record in raw_records:
                try:
                    result = self._process_record(record)
                    if result == "created":
                        created += 1
                    elif result == "duplicate":
                        duplicates += 1
                except Exception as e:
                    failed += 1
                    errors.append(str(e))
            if self.device.clear_device_logs_after_sync and created > 0:
                try:
                    connector.clear_attendance()
                except Exception as e:
                    errors.append(f"Clear logs failed: {e}")
        finally:
            connector.disconnect()
        self.sync_log.mark_complete(total, created, duplicates, failed, errors or None)
        self.device.update_sync_time()

    def _process_record(self, record):
        user_id = str(record.user_id)
        employee = self._get_employee(user_id)
        if not employee:
            return "skipped"
        timestamp = self._convert_timestamp(record.timestamp)
        if not timestamp:
            return "skipped"
        from zkteco_attendance.utils.zk_connector import ZKConnector
        log_type = ZKConnector.punch_type_to_log_type(getattr(record, "punch", 0))
        cache_key = (employee, timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        if cache_key in self._checkin_cache:
            return "duplicate"
        checkin = frappe.new_doc("Employee Checkin")
        checkin.employee = employee
        checkin.time = timestamp
        checkin.log_type = log_type
        checkin.device_id = self.device.name
        checkin.insert(ignore_permissions=True)
        self._checkin_cache.add(cache_key)
        return "created"

    def _load_employee_mappings(self):
        mappings = frappe.get_all("Device Employee Mapping",
            filters={"device": self.device.name, "active": 1},
            fields=["device_user_id", "employee"])
        for m in mappings:
            self._employee_cache[str(m.device_user_id)] = m.employee

    def _get_employee(self, user_id):
        if user_id in self._employee_cache:
            return self._employee_cache[user_id]
        employee = frappe.db.get_value("Device Employee Mapping",
            {"device": self.device.name, "device_user_id": user_id, "active": 1}, "employee")
        if employee:
            self._employee_cache[user_id] = employee
        return employee

    def _load_existing_checkins(self):
        since = frappe.utils.add_to_date(now_datetime(), days=-30)
        existing = frappe.db.sql(
            "SELECT employee, DATE_FORMAT(time, '%%Y-%%m-%%d %%H:%%i:%%S') as ts "
            "FROM `tabEmployee Checkin` WHERE time >= %s AND device_id = %s",
            (since, self.device.name), as_dict=True)
        for row in existing:
            self._checkin_cache.add((row.employee, row.ts))

    def _get_timezone(self):
        try:
            return pytz.timezone(self.device.time_zone or "UTC")
        except Exception:
            return pytz.utc

    def _convert_timestamp(self, ts):
        if not ts:
            return None
        try:
            if isinstance(ts, str):
                ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if ts.tzinfo is None:
                ts_aware = self.tz.localize(ts)
            else:
                ts_aware = ts.astimezone(self.tz)
            return ts_aware.astimezone(pytz.utc).replace(tzinfo=None)
        except Exception:
            return None

    def _get_since_datetime(self):
        if self.device.fetch_mode == "All Records":
            return None
        if self.device.last_sync_time:
            return get_datetime(self.device.last_sync_time)
        return frappe.utils.add_to_date(now_datetime(), days=-7)
