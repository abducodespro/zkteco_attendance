"""
Unit tests for ZKTeco Attendance sync engine.
Run with: bench run-tests --app zkteco_attendance
"""

import unittest
from unittest.mock import patch, MagicMock
import frappe
from frappe.utils import now_datetime


class TestSyncEngine(unittest.TestCase):

    def setUp(self):
        """Create a test Biometric Device."""
        if not frappe.db.exists("Biometric Device", "Test-ZK-Device"):
            device = frappe.get_doc({
                "doctype": "Biometric Device",
                "device_name": "Test-ZK-Device",
                "device_ip": "192.168.1.100",
                "port": 4370,
                "company": frappe.defaults.get_global_default("company"),
                "status": "Active",
                "time_zone": "UTC",
                "fetch_mode": "All Records",
                "auto_sync_enabled": 1,
                "sync_frequency": "5 Min",
            })
            device.insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        frappe.db.rollback()

    @patch("zkteco_attendance.zkteco_attendance.zk_client.ZK")
    def test_test_connection_success(self, mock_zk_class):
        """Test that test_connection returns correct structure on success."""
        mock_conn = MagicMock()
        mock_conn.get_serialnumber.return_value = "ABC123"
        mock_conn.get_firmware_version.return_value = "6.60"
        mock_conn.get_time.return_value = now_datetime()
        mock_conn.get_users.return_value = [MagicMock()] * 5
        mock_conn.get_attendance.return_value = [MagicMock()] * 20
        mock_zk_instance = MagicMock()
        mock_zk_instance.connect.return_value = mock_conn
        mock_zk_class.return_value = mock_zk_instance

        from zkteco_attendance.zkteco_attendance.zk_client import test_device_connection
        result = test_device_connection("Test-ZK-Device")

        self.assertTrue(result["success"])
        self.assertEqual(result["enrolled_users"], 5)
        self.assertEqual(result["attendance_logs"], 20)

    def test_get_employee_by_biometric_id_not_found(self):
        """Should return None when no employee matches."""
        from zkteco_attendance.zkteco_attendance.sync_engine import get_employee_by_biometric_id
        result = get_employee_by_biometric_id("NONEXISTENT_9999")
        self.assertIsNone(result)

    def test_checkin_duplicate_detection(self):
        """Duplicate checkin within 60s window should be detected."""
        from zkteco_attendance.zkteco_attendance.sync_engine import checkin_exists
        # Without any actual checkin record this should return falsy
        ts = now_datetime()
        result = checkin_exists("HR-EMP-00001", ts, "IN", "Test-ZK-Device")
        self.assertFalse(result)

    def test_get_punch_type_mapping(self):
        """Punch codes should map correctly to IN/OUT."""
        from zkteco_attendance.zkteco_attendance.zk_client import get_punch_type
        self.assertEqual(get_punch_type(0), "IN")
        self.assertEqual(get_punch_type(1), "OUT")
        self.assertEqual(get_punch_type(4), "IN")
        self.assertEqual(get_punch_type(5), "OUT")
        self.assertEqual(get_punch_type(99), "IN")  # default

    def test_is_overtime_punch(self):
        from zkteco_attendance.zkteco_attendance.zk_client import is_overtime_punch
        self.assertTrue(is_overtime_punch(4))
        self.assertTrue(is_overtime_punch(5))
        self.assertFalse(is_overtime_punch(0))
        self.assertFalse(is_overtime_punch(1))

    def test_resolve_log_types_alternates_in_out(self):
        """
        Devices that send punch=0 for every punch should still get
        alternating IN/OUT for a two-punch shift.
        """
        from zkteco_attendance.zkteco_attendance.sync_engine import resolve_log_types_for_day

        morning = now_datetime().replace(hour=7, minute=55, second=0, microsecond=0)
        evening = morning.replace(hour=17, minute=10)

        day_records = [
            {"punch": 0, "timestamp": morning},
            {"punch": 0, "timestamp": evening},  # device also sends punch=0
        ]
        result = resolve_log_types_for_day(day_records)
        self.assertEqual(result, ["IN", "OUT"])

    def test_resolve_log_types_preserves_overtime_punches(self):
        """Explicit OT In/Out punches (4/5) keep their meaning and are not
        part of the regular IN/OUT alternation."""
        from zkteco_attendance.zkteco_attendance.sync_engine import resolve_log_types_for_day

        t1 = now_datetime().replace(hour=8, minute=0, second=0, microsecond=0)
        t2 = t1.replace(hour=17, minute=0)
        t3 = t1.replace(hour=18, minute=0)  # OT in
        t4 = t1.replace(hour=20, minute=0)  # OT out

        day_records = [
            {"punch": 0, "timestamp": t1},  # regular IN
            {"punch": 0, "timestamp": t2},  # regular OUT
            {"punch": 4, "timestamp": t3},  # OT in
            {"punch": 5, "timestamp": t4},  # OT out
        ]
        result = resolve_log_types_for_day(day_records)
        self.assertEqual(result, ["IN", "OUT", "IN", "OUT"])


class TestBiometricDeviceValidation(unittest.TestCase):

    def test_invalid_ip_rejected(self):
        """Device with invalid IP should fail validation."""
        device = frappe.get_doc({
            "doctype": "Biometric Device",
            "device_name": "Bad-IP-Device",
            "device_ip": "not_an_ip!!!",
            "port": 4370,
            "company": frappe.defaults.get_global_default("company"),
        })
        self.assertRaises(frappe.ValidationError, device.validate)

    def test_invalid_port_rejected(self):
        device = frappe.get_doc({
            "doctype": "Biometric Device",
            "device_name": "Bad-Port-Device",
            "device_ip": "192.168.1.1",
            "port": 99999,
            "company": frappe.defaults.get_global_default("company"),
        })
        self.assertRaises(frappe.ValidationError, device.validate)
