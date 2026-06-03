"""
ZKConnector: Low-level communication layer for ZKTeco devices using pyzk.

Supports: K40, MB20, UFace, iFace, F18, SpeedFace, and other ZKTeco models.
"""
import frappe
from frappe import _
import socket
import logging

logger = logging.getLogger(__name__)

try:
    from zk import ZK, const as zk_const
    ZK_AVAILABLE = True
except ImportError:
    ZK_AVAILABLE = False
    logger.warning("pyzk library not installed. Install with: pip install pyzk")


class ZKConnector:
    """
    Manages the lifecycle of a connection to a ZKTeco biometric device.

    Usage:
        connector = ZKConnector(device_doc)
        conn = connector.connect()
        attendance = conn.get_attendance()
        connector.disconnect()

    Or as context manager:
        with ZKConnector(device_doc) as conn:
            attendance = conn.get_attendance()
    """

    TIMEOUT = 10  # seconds
    FORCE_UDP = False

    def __init__(self, device_doc):
        """
        Args:
            device_doc: Frappe Document of type "Biometric Device"
        """
        if not ZK_AVAILABLE:
            frappe.throw(
                _(
                    "pyzk library is not installed. "
                    "Run: <code>pip install pyzk</code> in your bench environment."
                )
            )

        self.device_doc = device_doc
        self.device_ip = device_doc.device_ip
        self.port = int(device_doc.port or 4370)
        self.password = (
            int(device_doc.get_password("connection_password") or 0)
            if device_doc.connection_password
            else 0
        )
        self._zk = None
        self._conn = None

    # ─────────────────────────────────────────
    #  Context Manager Protocol
    # ─────────────────────────────────────────

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False  # don't suppress exceptions

    # ─────────────────────────────────────────
    #  Connection Management
    # ─────────────────────────────────────────

    def connect(self):
        """
        Establish connection to the ZKTeco device.

        Returns:
            zk.ZK connection object

        Raises:
            ConnectionError: if the device cannot be reached
            Exception: for auth/protocol failures
        """
        if self._conn:
            return self._conn

        self._validate_network_reachable()

        self._zk = ZK(
            self.device_ip,
            port=self.port,
            timeout=self.TIMEOUT,
            password=self.password,
            force_udp=self.FORCE_UDP,
            ommit_ping=False,
        )

        try:
            self._conn = self._zk.connect()
            self._conn.disable_device()  # Disable while reading to prevent data loss
            logger.info(f"ZKConnector: Connected to {self.device_ip}:{self.port}")
            return self._conn
        except Exception as e:
            self._conn = None
            self._zk = None
            error_msg = self._humanize_error(e)
            frappe.log_error(
                title=f"ZKTeco Connection Failed: {self.device_doc.name}",
                message=f"Device: {self.device_ip}:{self.port}\nError: {error_msg}",
            )
            raise ConnectionError(
                f"Cannot connect to device {self.device_doc.name} ({self.device_ip}:{self.port}): {error_msg}"
            )

    def disconnect(self):
        """Safely disconnect from the device, re-enabling it first."""
        if self._conn:
            try:
                self._conn.enable_device()
                self._conn.disconnect()
                logger.info(f"ZKConnector: Disconnected from {self.device_ip}:{self.port}")
            except Exception as e:
                logger.warning(f"ZKConnector: Error during disconnect: {e}")
            finally:
                self._conn = None
                self._zk = None

    # ─────────────────────────────────────────
    #  Device Information
    # ─────────────────────────────────────────

    def test_connection(self) -> dict:
        """
        Test the connection and return device metadata.

        Returns:
            dict with device_serial, firmware_version, device_time,
            user_count, attendance_count
        """
        try:
            conn = self.connect()

            serial = conn.get_serialnumber()
            firmware = conn.get_firmware_version()
            device_time = conn.get_time()
            users = conn.get_users()
            attendance = conn.get_attendance()

            return {
                "device_ip": self.device_ip,
                "port": self.port,
                "device_serial": serial,
                "firmware_version": firmware,
                "device_time": str(device_time),
                "enrolled_users": len(users),
                "attendance_records": len(attendance),
            }
        finally:
            self.disconnect()

    # ─────────────────────────────────────────
    #  Data Retrieval
    # ─────────────────────────────────────────

    def get_attendance_records(self, since_datetime=None) -> list:
        """
        Fetch attendance records from device.

        Args:
            since_datetime: If set (datetime), only return records after this time.
                            The ZK protocol doesn't support server-side filtering,
                            so we filter client-side.

        Returns:
            List of zk.Attendance objects
        """
        conn = self.connect()
        try:
            all_records = conn.get_attendance()
            logger.info(
                f"ZKConnector: Fetched {len(all_records)} raw records from {self.device_ip}"
            )

            if since_datetime and all_records:
                filtered = [
                    r for r in all_records
                    if r.timestamp and r.timestamp > since_datetime
                ]
                logger.info(
                    f"ZKConnector: Filtered to {len(filtered)} records after {since_datetime}"
                )
                return filtered

            return all_records
        except Exception as e:
            logger.error(f"ZKConnector: Error fetching attendance: {e}")
            raise

    def get_users(self) -> list:
        """
        Fetch enrolled users from the device.

        Returns:
            List of zk.User objects
        """
        conn = self.connect()
        return conn.get_users()

    def clear_attendance(self):
        """
        Clear all attendance records from the device.
        Only call after successful sync!
        """
        conn = self.connect()
        conn.clear_attendance()
        logger.warning(
            f"ZKConnector: Cleared attendance logs on {self.device_ip}"
        )

    def sync_device_time(self):
        """Set the device time to the current server time."""
        import datetime
        conn = self.connect()
        conn.set_time(datetime.datetime.now())
        logger.info(f"ZKConnector: Synced time on {self.device_ip}")

    # ─────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────

    def _validate_network_reachable(self):
        """Quick TCP reachability check before attempting full ZK connection."""
        try:
            sock = socket.create_connection(
                (self.device_ip, self.port), timeout=5
            )
            sock.close()
        except socket.timeout:
            raise ConnectionError(
                f"Device {self.device_ip}:{self.port} timed out (network timeout)"
            )
        except ConnectionRefusedError:
            raise ConnectionError(
                f"Device {self.device_ip}:{self.port} refused the connection (device may be busy or powered off)"
            )
        except OSError as e:
            raise ConnectionError(
                f"Network error reaching {self.device_ip}:{self.port}: {str(e)}"
            )

    @staticmethod
    def _humanize_error(e: Exception) -> str:
        """Convert raw exception to user-friendly message."""
        msg = str(e).lower()
        if "timeout" in msg:
            return "Connection timed out — check network/firewall settings"
        if "refused" in msg:
            return "Connection refused — device may be busy or wrong port"
        if "authentication" in msg or "password" in msg:
            return "Authentication failed — check connection password"
        if "no route" in msg:
            return "No route to host — device may be on a different network"
        return str(e)

    @staticmethod
    def punch_type_to_log_type(punch_type: int) -> str:
        """
        Convert ZKTeco punch type integer to ERPNext log type string.

        ZKTeco punch codes:
          0 = Check In
          1 = Check Out
          2 = Break Out
          3 = Break In
          4 = Overtime In
          5 = Overtime Out
        """
        mapping = {
            0: "IN",
            1: "OUT",
            2: "OUT",   # Break Out treated as OUT
            3: "IN",    # Break In treated as IN
            4: "IN",    # Overtime In
            5: "OUT",   # Overtime Out
        }
        return mapping.get(punch_type, "IN")  # Default to IN if unknown
