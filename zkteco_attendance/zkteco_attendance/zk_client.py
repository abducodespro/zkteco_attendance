"""
ZKTeco Device Client
Wraps pyzk library with error handling, logging, and timezone support.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime
import pytz
from datetime import datetime


def get_zk_connection(device_doc):
    """
    Establish a connection to a ZKTeco device.
    Returns a ZK instance (connected) or raises an exception.
    """
    try:
        from zk import ZK, const
    except ImportError:
        frappe.throw(
            _("pyzk library is not installed. Run: pip install pyzk"),
            title=_("Missing Dependency")
        )

    ip = device_doc.device_ip
    port = int(device_doc.port or 4370)
    password = device_doc.get_password("connection_password") or 0
    timeout = 10

    zk = ZK(ip, port=port, timeout=timeout, password=int(password) if password else 0, force_udp=False, ommit_ping=False)

    try:
        conn = zk.connect()
        return conn, zk
    except Exception as e:
        frappe.log_error(
            message=f"ZKTeco connection failed for device {device_doc.name} ({ip}:{port}): {str(e)}",
            title="ZKTeco Connection Error"
        )
        raise frappe.ValidationError(
            _("Cannot connect to device {0} at {1}:{2}. Error: {3}").format(
                device_doc.device_name, ip, port, str(e)
            )
        )


def test_device_connection(device_name):
    """
    Test connection to a device and return device info.
    Called from the form button and the API.
    """
    device = frappe.get_doc("Biometric Device", device_name)

    result = {
        "success": False,
        "device_name": device_name,
        "ip": device.device_ip,
        "port": device.port,
    }

    conn = None
    zk = None
    try:
        conn, zk = get_zk_connection(device)

        serial = conn.get_serialnumber()
        firmware = conn.get_firmware_version()
        device_time = conn.get_time()
        users = conn.get_users()
        attendance = conn.get_attendance()

        result.update({
            "success": True,
            "serial_number": serial,
            "firmware_version": firmware,
            "device_time": str(device_time),
            "enrolled_users": len(users) if users else 0,
            "attendance_logs": len(attendance) if attendance else 0,
            "message": _("Connection successful"),
        })

        # Update device status
        frappe.db.set_value("Biometric Device", device_name, "status", "Active")

    except Exception as e:
        result["error"] = str(e)
        result["message"] = _("Connection failed: {0}").format(str(e))
        frappe.db.set_value("Biometric Device", device_name, "status", "Inactive")

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

    frappe.db.commit()
    return result


def pull_attendance_from_device(device_doc, fetch_mode="New Records Only"):
    """
    Pull attendance logs from a ZKTeco device.
    Returns list of dicts: {uid, user_id, timestamp, punch, status}
    """
    conn = None
    zk = None
    records = []

    try:
        conn, zk = get_zk_connection(device_doc)
        attendance_logs = conn.get_attendance()

        if not attendance_logs:
            return records

        tz_name = device_doc.time_zone or "UTC"
        try:
            device_tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            device_tz = pytz.UTC

        for log in attendance_logs:
            # Convert device local time → UTC-aware datetime
            try:
                if hasattr(log.timestamp, 'tzinfo') and log.timestamp.tzinfo:
                    utc_dt = log.timestamp.astimezone(pytz.UTC)
                else:
                    local_dt = device_tz.localize(log.timestamp)
                    utc_dt = local_dt.astimezone(pytz.UTC)
            except Exception:
                utc_dt = log.timestamp

            records.append({
                "uid": log.uid,
                "user_id": str(log.user_id),
                "timestamp": utc_dt.replace(tzinfo=None),  # store naive UTC in Frappe
                "punch": log.punch,      # 0=Check In, 1=Check Out, 4=OT In, 5=OT Out
                "status": log.status,
            })

        # Clear logs if configured
        if device_doc.clear_device_logs_after_sync:
            try:
                conn.clear_attendance()
                frappe.log_error(
                    message=f"Cleared attendance logs on device {device_doc.name} after sync.",
                    title="ZKTeco: Logs Cleared"
                )
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to clear logs on device {device_doc.name}: {str(e)}",
                    title="ZKTeco: Clear Logs Failed"
                )

    except Exception as e:
        frappe.log_error(
            message=f"Error pulling attendance from {device_doc.name}: {str(e)}",
            title="ZKTeco Pull Error"
        )
        raise
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

    return records


def get_punch_type(punch_code):
    """Map ZKTeco punch codes to ERPNext check-in log types."""
    # 0 = Check In, 1 = Check Out, 2 = Break Out, 3 = Break In, 4 = OT In, 5 = OT Out
    in_codes = {0, 4}
    out_codes = {1, 2, 3, 5}

    if punch_code in in_codes:
        return "IN"
    elif punch_code in out_codes:
        return "OUT"
    else:
        return "IN"  # default
