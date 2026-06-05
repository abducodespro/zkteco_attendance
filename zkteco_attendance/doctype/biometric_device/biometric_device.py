# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
import re


class BiometricDevice(Document):

    def validate(self):
        self._validate_ip_address()
        self._validate_port()
        self._prevent_duplicate_device()

    def _validate_ip_address(self):
        ip_pattern = re.compile(
            r"^(\d{1,3}\.){3}\d{1,3}$|"
            r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
        )
        if not ip_pattern.match(self.device_ip):
            frappe.throw(_("Invalid IP address or hostname: {0}").format(self.device_ip))

    def _validate_port(self):
        if not (1 <= int(self.port) <= 65535):
            frappe.throw(_("Port must be between 1 and 65535"))

    def _prevent_duplicate_device(self):
        existing = frappe.db.get_all(
            "Biometric Device",
            filters={"device_ip": self.device_ip, "port": self.port, "name": ["!=", self.name]},
            pluck="name",
        )
        if existing:
            frappe.throw(_("A device with IP {0}:{1} already exists: {2}").format(
                self.device_ip, self.port, ", ".join(existing)
            ))

    def update_sync_time(self, commit=True):
        self.db_set("last_sync_time", now_datetime(), update_modified=False)
        if commit:
            frappe.db.commit()


def has_permission(doc, ptype, user):
    if frappe.has_role("System Manager", user=user):
        return True
    if frappe.has_role("HR Manager", user=user):
        return True
    if frappe.has_role("Attendance Manager", user=user) and ptype in ("read", "write", "create"):
        return True
    return False


def before_save(doc, method):
    doc.validate()


def on_trash(doc, method):
    frappe.db.delete("Device Employee Mapping", {"device": doc.name})


@frappe.whitelist()
def test_connection(device_name):
    from zkteco_attendance.utils.zk_connector import ZKConnector
    device = frappe.get_doc("Biometric Device", device_name)
    connector = ZKConnector(device)
    try:
        result = connector.test_connection()
        return {"success": True, "message": _("Connection successful"), "data": result}
    except Exception as e:
        frappe.log_error(title=f"ZKTeco Connection Test Failed: {device_name}", message=str(e))
        return {"success": False, "message": str(e), "data": None}


@frappe.whitelist()
def sync_device(device_name, triggered_by="Manual"):
    frappe.has_permission("Biometric Device", throw=True)
    device = frappe.get_doc("Biometric Device", device_name)
    if device.status != "Active":
        frappe.throw(_("Device {0} is not Active").format(device_name))
    frappe.enqueue(
        "zkteco_attendance.utils.sync_engine.run_sync_for_device",
        device_name=device_name,
        triggered_by=triggered_by,
        queue="long",
        timeout=600,
        job_name=f"zk_sync_{device_name}",
    )
    return {"success": True, "message": _("Sync job enqueued for device {0}").format(device_name)}


@frappe.whitelist()
def sync_all_devices():
    frappe.has_permission("Biometric Device", throw=True)
    devices = frappe.get_all("Biometric Device", filters={"status": "Active"}, pluck="name")
    if not devices:
        return {"success": False, "message": _("No active devices found")}
    for device_name in devices:
        frappe.enqueue(
            "zkteco_attendance.utils.sync_engine.run_sync_for_device",
            device_name=device_name,
            triggered_by="Manual",
            queue="long",
            timeout=600,
            job_name=f"zk_sync_{device_name}",
        )
    return {"success": True, "message": _("Sync jobs enqueued for {0} device(s)").format(len(devices))}


@frappe.whitelist()
def get_device_status(device_name):
    device = frappe.get_doc("Biometric Device", device_name)
    last_log = frappe.get_all(
        "Attendance Sync Log",
        filters={"device": device_name},
        fields=["sync_status", "end_time", "total_records_pulled", "new_records_created", "failed_records"],
        order_by="creation desc",
        limit=1,
    )
    return {
        "device_name": device_name,
        "status": device.status,
        "last_sync_time": str(device.last_sync_time) if device.last_sync_time else None,
        "last_log": last_log[0] if last_log else None,
    }


@frappe.whitelist()
def get_sync_logs(device_name=None, limit=20):
    filters = {}
    if device_name:
        filters["device"] = device_name
    return frappe.get_all(
        "Attendance Sync Log",
        filters=filters,
        fields=["name","device","start_time","end_time","total_records_pulled",
                "new_records_created","duplicate_records","failed_records",
                "sync_status","triggered_by","error_details"],
        order_by="creation desc",
        limit=int(limit),
    )


@frappe.whitelist()
def get_dashboard_stats():
    total = frappe.db.count("Biometric Device")
    active = frappe.db.count("Biometric Device", {"status": "Active"})
    today = frappe.utils.today()
    today_checkins = frappe.db.count("Employee Checkin", {
        "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
        "device_id": ["is", "set"],
    })
    yesterday = frappe.utils.add_to_date(now_datetime(), hours=-24)
    failed_syncs = frappe.db.count("Attendance Sync Log", {
        "sync_status": "Failed", "start_time": [">=", yesterday]
    })
    last_sync = frappe.get_all("Attendance Sync Log",
        fields=["device","end_time","sync_status"], order_by="creation desc", limit=1)
    return {
        "total_devices": total,
        "active_devices": active,
        "inactive_devices": total - active,
        "today_checkins": today_checkins,
        "failed_syncs_24h": failed_syncs,
        "last_sync": last_sync[0] if last_sync else None,
    }
