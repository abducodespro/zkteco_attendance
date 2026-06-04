"""
Biometric Device DocType controller.
Manages ZKTeco device configuration, connection testing, and sync triggering.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime
import re


class BiometricDevice(Document):
    """Controller for Biometric Device DocType."""

    def validate(self):
        """Validate device configuration before saving."""
        self._validate_ip_address()
        self._validate_port()
        self._validate_sync_settings()
        self._prevent_duplicate_device()

    def before_save(self, doc=None, method=None):
        """Hook called before saving."""
        if doc:
            doc.validate()

    def on_trash(self, doc=None, method=None):
        """Clean up related records when device is deleted."""
        device_name = self.name if not doc else doc.name
        # Remove related mappings
        frappe.db.delete("Device Employee Mapping", {"device": device_name})
        frappe.msgprint(
            _("Deleted all employee mappings for device {0}").format(device_name)
        )

    def _validate_ip_address(self):
        """Validate that the device IP is a valid IP address or hostname."""
        ip_pattern = re.compile(
            r"^(\d{1,3}\.){3}\d{1,3}$|"
            r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
        )
        if not ip_pattern.match(self.device_ip):
            frappe.throw(_("Invalid IP address or hostname: {0}").format(self.device_ip))

        # Validate IP octets if it's an IP
        if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", self.device_ip):
            octets = self.device_ip.split(".")
            for octet in octets:
                if int(octet) > 255:
                    frappe.throw(_("Invalid IP address: {0}").format(self.device_ip))

    def _validate_port(self):
        """Validate port number is within valid range."""
        if not (1 <= self.port <= 65535):
            frappe.throw(_("Port must be between 1 and 65535"))

    def _validate_sync_settings(self):
        """Validate sync-related settings."""
        if self.auto_sync_enabled and not self.sync_frequency:
            frappe.throw(_("Sync Frequency is required when Auto Sync is enabled"))

    def _prevent_duplicate_device(self):
        """Prevent duplicate device IPs on the same network."""
        existing = frappe.db.get_all(
            "Biometric Device",
            filters={
                "device_ip": self.device_ip,
                "port": self.port,
                "name": ["!=", self.name],
            },
            pluck="name",
        )
        if existing:
            frappe.throw(
                _("A device with IP {0} and port {1} already exists: {2}").format(
                    self.device_ip, self.port, ", ".join(existing)
                )
            )

    def update_sync_time(self, commit=True):
        """Update the last sync time to now."""
        self.db_set("last_sync_time", now_datetime(), update_modified=False)
        if commit:
            frappe.db.commit()

    @frappe.whitelist()
    def test_connection_from_form(self):
        """Test connection from the form button."""
        return test_connection(self.name)

    @frappe.whitelist()
    def sync_now_from_form(self):
        """Trigger sync from the form button."""
        return sync_device(self.name, triggered_by="Manual")


def has_permission(doc, ptype, user):
    """Custom permission check."""
    if frappe.has_role("System Manager", user=user):
        return True
    if frappe.has_role("HR Manager", user=user):
        return True
    if frappe.has_role("Attendance Manager", user=user) and ptype in ("read", "write", "create"):
        return True
    return False


def before_save(doc, method):
    """Document event hook."""
    doc.validate()


def on_trash(doc, method):
    """Document event hook for deletion."""
    frappe.db.delete("Device Employee Mapping", {"device": doc.name})


# ─────────────────────────────────────────
#  Whitelisted API Methods
# ─────────────────────────────────────────

@frappe.whitelist()
def test_connection(device_name: str) -> dict:
    """
    Test connectivity to a ZKTeco device.

    Returns a dict with device info or error details.
    """
    from zkteco_attendance.utils.zk_connector import ZKConnector

    device = frappe.get_doc("Biometric Device", device_name)
    connector = ZKConnector(device)

    try:
        result = connector.test_connection()
        return {
            "success": True,
            "message": _("Connection successful"),
            "data": result,
        }
    except Exception as e:
        frappe.log_error(
            title=f"ZKTeco Connection Test Failed: {device_name}",
            message=str(e),
        )
        return {
            "success": False,
            "message": str(e),
            "data": None,
        }


@frappe.whitelist()
def sync_device(device_name: str, triggered_by: str = "Manual") -> dict:
    """
    Enqueue a background sync job for a specific device.
    """
    frappe.has_permission("Biometric Device", throw=True)

    # Validate device exists and is active
    device = frappe.get_doc("Biometric Device", device_name)
    if device.status != "Active":
        frappe.throw(_("Device {0} is not Active").format(device_name))

    frappe.enqueue(
        "zkteco_attendance.utils.sync_engine.run_sync_for_device",
        device_name=device_name,
        triggered_by=triggered_by,
        queue="long",
        timeout=600,
        is_async=True,
        job_name=f"zk_sync_{device_name}",
    )

    return {
        "success": True,
        "message": _("Sync job enqueued for device {0}. Check Attendance Sync Log for results.").format(
            device_name
        ),
    }


@frappe.whitelist()
def sync_all_devices() -> dict:
    """
    Enqueue sync for all active devices.
    """
    frappe.has_permission("Biometric Device", throw=True)

    devices = frappe.get_all(
        "Biometric Device",
        filters={"status": "Active"},
        pluck="name",
    )

    if not devices:
        return {"success": False, "message": _("No active devices found")}

    for device_name in devices:
        frappe.enqueue(
            "zkteco_attendance.utils.sync_engine.run_sync_for_device",
            device_name=device_name,
            triggered_by="Manual",
            queue="long",
            timeout=600,
            is_async=True,
            job_name=f"zk_sync_{device_name}",
        )

    return {
        "success": True,
        "message": _("Sync jobs enqueued for {0} device(s)").format(len(devices)),
    }


@frappe.whitelist()
def get_device_status(device_name: str) -> dict:
    """
    Return a quick status snapshot for a device (last sync, status).
    """
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
def get_sync_logs(device_name: str = None, limit: int = 20) -> list:
    """
    Return recent sync logs, optionally filtered by device.
    """
    filters = {}
    if device_name:
        filters["device"] = device_name

    logs = frappe.get_all(
        "Attendance Sync Log",
        filters=filters,
        fields=[
            "name", "device", "start_time", "end_time", "total_records_pulled",
            "new_records_created", "duplicate_records", "failed_records",
            "sync_status", "triggered_by", "error_details",
        ],
        order_by="creation desc",
        limit=int(limit),
    )
    return logs


@frappe.whitelist()
def get_dashboard_stats() -> dict:
    """
    Return stats for the ZKTeco dashboard page.
    """
    total_devices = frappe.db.count("Biometric Device")
    active_devices = frappe.db.count("Biometric Device", {"status": "Active"})
    inactive_devices = total_devices - active_devices

    # Today's checkins created via ZK sync (flagged in remarks)
    today = frappe.utils.today()
    today_checkins = frappe.db.count(
        "Employee Checkin",
        {
            "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
            "device_id": ["is", "set"],
        },
    )

    # Failed syncs in last 24h
    yesterday = frappe.utils.add_to_date(now_datetime(), hours=-24)
    failed_syncs = frappe.db.count(
        "Attendance Sync Log",
        {"sync_status": "Failed", "start_time": [">=", yesterday]},
    )

    # Last sync
    last_sync = frappe.get_all(
        "Attendance Sync Log",
        fields=["device", "end_time", "sync_status"],
        order_by="creation desc",
        limit=1,
    )

    return {
        "total_devices": total_devices,
        "active_devices": active_devices,
        "inactive_devices": inactive_devices,
        "today_checkins": today_checkins,
        "failed_syncs_24h": failed_syncs,
        "last_sync": last_sync[0] if last_sync else None,
    }
