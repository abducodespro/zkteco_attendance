"""
Unit tests for the ZKTeco attendance processor overtime keys.

Regression guard: the OT calculation must expose the total under the
`overtime_hours` key (matching the Attendance Summary Detail DB field and
all consumers). A previous refactor renamed it to `ot_hours`, which made
Total Overtime Hours always 0 in Attendance Summary and on the Daily
Checkins page while the per-category chips still showed values.

Run with: bench run-tests --app zkteco_attendance
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import get_datetime


def _mk_checkin(name, time_str, log_type):
    return {"name": name, "time": get_datetime(time_str), "log_type": log_type,
            "is_overtime": False, "manually_edited": False, "edited_by": "", "edited_at": ""}


def _day_shift(**overrides):
    shift = {
        "name": "TEST-SHIFT",
        "start_time": "08:00:00",
        "end_time": "17:00:00",
        "is_night_shift": 0,
        "full_day_hours": 8,
        "half_day_hours": 4,
        "standard_working_hours": 8,
        "working_hours_method": "First IN - Last OUT",
        "missing_checkin_action": "Mark as Invalid",
        "late_entry_grace": 0,
        "early_exit_grace": 0,
        "saturday_mode": "Full Day",
        "saturday_half_day_hours": 4,
        "enable_overtime": 1,
        "overtime_calculation_method": "Fixed Windows",
        "overtime_threshold_minutes": 0,
        "max_overtime_hours_per_day": 0,
        "standard_start_time": "08:00:00",
        "night_ot_start_time": "22:00:00",
        "night_ot_end_time": "06:00:00",
    }
    shift.update(overrides)
    return shift


class TestOvertimeKeys(unittest.TestCase):

    def test_calc_overtime_hours_returns_overtime_hours_key(self):
        """The total OT must be under `overtime_hours`, not `ot_hours`."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        checkins = [
            _mk_checkin("C1", "2026-08-10 06:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = calc_overtime_hours(checkins, _day_shift(), total_hours=11.0)

        self.assertIn("overtime_hours", result)
        self.assertNotIn("ot_hours", result)
        # 11h worked, 8h standard -> 3h day OT, 0h night OT
        self.assertAlmostEqual(result["overtime_hours"], 3.0, places=2)
        self.assertAlmostEqual(result["day_ot_hours"], 3.0, places=2)
        self.assertAlmostEqual(result["night_ot_hours"], 0.0, places=2)

    def test_calc_overtime_hours_zero_dict_has_overtime_hours_key(self):
        """When overtime is disabled, the zero dict still carries the key."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        shift = _day_shift(enable_overtime=0)
        result = calc_overtime_hours([], shift, total_hours=0.0)
        self.assertIn("overtime_hours", result)
        self.assertEqual(result["overtime_hours"], 0.0)

    def test_classify_day_returns_overtime_hours_key(self):
        """classify_day must surface the OT total as `overtime_hours`."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        checkins = [
            _mk_checkin("C1", "2026-08-10 06:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = classify_day(checkins, _day_shift(), "First IN - Last OUT", "Mark as Invalid")

        self.assertEqual(result["status"], "Present")
        self.assertAlmostEqual(result["hours"], 11.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 3.0, places=2)
        self.assertAlmostEqual(result["day_ot_hours"], 3.0, places=2)

    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_holidays_in_range")
    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_shift_for_employee")
    def test_process_employee_aggregates_overtime_hours(self, mock_shift, mock_holidays):
        """
        The headline regression: process_employee must roll the per-day
        `overtime_hours` up so Attendance Summary's Total Overtime Hours
        gets populated. Before the fix this stayed 0.0 forever.
        """
        from zkteco_attendance.zkteco_attendance.attendance_processor import process_employee

        mock_shift.return_value = _day_shift()
        mock_holidays.return_value = set()

        checkins = [
            _mk_checkin("C1", "2026-08-10 06:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = process_employee(
            employee="HR-EMP-00001",
            from_date="2026-08-10",
            to_date="2026-08-10",
            checkin_list=checkins,
            default_shift_name=None,
            doc_method="First IN - Last OUT",
            doc_missing_action="Mark as Invalid",
        )

        self.assertEqual(result["working_days"], 1.0)
        self.assertAlmostEqual(result["total_working_hours"], 11.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 3.0, places=2)
        self.assertAlmostEqual(result["day_ot_hours"], 3.0, places=2)
        self.assertAlmostEqual(result["night_ot_hours"], 0.0, places=2)
        self.assertEqual(result["overtime_days"], 1)

    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_holidays_in_range")
    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_shift_for_employee")
    def test_process_employee_night_overtime(self, mock_shift, mock_holidays):
        """Night-shift window hours are reported separately and in the total."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import process_employee

        mock_shift.return_value = _day_shift(is_night_shift=1, end_time="06:00:00")
        mock_holidays.return_value = set()

        # 17:00 -> next-day 06:00 : 8h of night-window (22:00-06:00) overtime
        checkins = [
            _mk_checkin("C1", "2026-08-10 17:00:00", "IN"),
            _mk_checkin("C2", "2026-08-11 06:00:00", "OUT"),
        ]
        result = process_employee(
            employee="HR-EMP-00001",
            from_date="2026-08-10",
            to_date="2026-08-10",
            checkin_list=checkins,
            default_shift_name=None,
            doc_method="First IN - Last OUT",
            doc_missing_action="Mark as Invalid",
        )

        self.assertAlmostEqual(result["total_working_hours"], 13.0, places=2)
        self.assertAlmostEqual(result["night_ot_hours"], 8.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 8.0, places=2)


if __name__ == "__main__":
    unittest.main()
