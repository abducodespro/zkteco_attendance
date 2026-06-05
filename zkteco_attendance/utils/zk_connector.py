# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from frappe import _
import socket
import logging

logger = logging.getLogger(__name__)

try:
    from zk import ZK
    ZK_AVAILABLE = True
except ImportError:
    ZK_AVAILABLE = False


class ZKConnector:

    TIMEOUT = 10

    def __init__(self, device_doc):
        if not ZK_AVAILABLE:
            frappe.throw(_("pyzk library not installed. Run: pip install pyzk"))
        self.device_doc = device_doc
        self.device_ip = device_doc.device_ip
        self.port = int(device_doc.port or 4370)
        self.password = 0
        if device_doc.connection_password:
            try:
                self.password = int(device_doc.get_password("connection_password") or 0)
            except Exception:
                self.password = 0
        self._zk = None
        self._conn = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def connect(self):
        if self._conn:
            return self._conn
        self._check_reachable()
        self._zk = ZK(self.device_ip, port=self.port, timeout=self.TIMEOUT,
                      password=self.password, force_udp=False, ommit_ping=False)
        try:
            self._conn = self._zk.connect()
            self._conn.disable_device()
            return self._conn
        except Exception as e:
            self._conn = None
            self._zk = None
            raise ConnectionError(f"Cannot connect to {self.device_ip}:{self.port}: {e}")

    def disconnect(self):
        if self._conn:
            try:
                self._conn.enable_device()
                self._conn.disconnect()
            except Exception:
                pass
            finally:
                self._conn = None
                self._zk = None

    def test_connection(self):
        try:
            conn = self.connect()
            return {
                "device_ip": self.device_ip,
                "port": self.port,
                "device_serial": conn.get_serialnumber(),
                "firmware_version": conn.get_firmware_version(),
                "device_time": str(conn.get_time()),
                "enrolled_users": len(conn.get_users()),
                "attendance_records": len(conn.get_attendance()),
            }
        finally:
            self.disconnect()

    def get_attendance_records(self, since_datetime=None):
        conn = self.connect()
        records = conn.get_attendance()
        if since_datetime and records:
            records = [r for r in records if r.timestamp and r.timestamp > since_datetime]
        return records

    def get_users(self):
        conn = self.connect()
        return conn.get_users()

    def clear_attendance(self):
        conn = self.connect()
        conn.clear_attendance()

    def _check_reachable(self):
        try:
            sock = socket.create_connection((self.device_ip, self.port), timeout=5)
            sock.close()
        except socket.timeout:
            raise ConnectionError(f"Device {self.device_ip}:{self.port} timed out")
        except ConnectionRefusedError:
            raise ConnectionError(f"Device {self.device_ip}:{self.port} refused connection")
        except OSError as e:
            raise ConnectionError(f"Network error: {e}")

    @staticmethod
    def punch_type_to_log_type(punch_type):
        return {0: "IN", 1: "OUT", 2: "OUT", 3: "IN", 4: "IN", 5: "OUT"}.get(punch_type, "IN")
