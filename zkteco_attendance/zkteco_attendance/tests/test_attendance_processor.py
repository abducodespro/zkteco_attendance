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
from datetime import date, datetime
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

        mock_shift.return_value = _day_shift(is_night_shift=1, start_time="17:00:00", end_time="06:00:00")
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


class TestGraceAndShiftOvertime(unittest.TestCase):
    """
    Grace periods (Late Entry / Early Exit) are deducted from working hours
    and the shift's Start/End Time drive overtime when the shift uses the
    'After Shift End Time' calculation method.
    """

    def test_classify_day_late_entry_grace_deducts_minutes(self):
        """First IN beyond Start Time + Late Entry Grace reduces hours + flags."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        shift = _day_shift(late_entry_grace=10)
        checkins = [
            _mk_checkin("C1", "2026-08-10 08:30:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = classify_day(checkins, shift, "First IN - Last OUT", "Mark as Invalid")

        # raw 8.5h, 20 min beyond the 10 min grace -> 8.5 - 20/60
        self.assertTrue(result["is_late"])
        self.assertFalse(result["is_early_exit"])
        self.assertAlmostEqual(result["late_minutes"], 20.0, places=1)
        self.assertAlmostEqual(result["hours"], 8.5 - 20.0 / 60.0, places=2)
        self.assertEqual(result["status"], "Present")

    def test_classify_day_within_grace_is_not_late(self):
        """Arriving inside the grace window is not late and loses no hours."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        shift = _day_shift(late_entry_grace=15)
        checkins = [
            _mk_checkin("C1", "2026-08-10 08:10:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = classify_day(checkins, shift, "First IN - Last OUT", "Mark as Invalid")

        self.assertFalse(result["is_late"])
        self.assertAlmostEqual(result["hours"], 8.8333, places=2)
        self.assertEqual(result["status"], "Present")

    def test_classify_day_late_entry_can_drop_to_absent(self):
        """A big late arrival reduces effective hours below the half-day mark."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        shift = _day_shift(late_entry_grace=0)  # 08:00 start, half day at 4h
        checkins = [
            _mk_checkin("C1", "2026-08-10 12:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 17:00:00", "OUT"),
        ]
        result = classify_day(checkins, shift, "First IN - Last OUT", "Mark as Invalid")

        # raw 5h, 4h late -> 1h effective -> Absent
        self.assertTrue(result["is_late"])
        self.assertEqual(result["status"], "Absent")
        self.assertAlmostEqual(result["hours"], 1.0, places=2)

    def test_classify_day_early_exit_grace_deducts_minutes(self):
        """Last OUT before End Time - Early Exit Grace reduces hours + flags."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        shift = _day_shift(early_exit_grace=15)
        checkins = [
            _mk_checkin("C1", "2026-08-10 08:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 16:30:00", "OUT"),
        ]
        result = classify_day(checkins, shift, "First IN - Last OUT", "Mark as Invalid")

        # raw 8.5h, 30 min early beyond the 15 min grace -> 8.5 - 15/60
        self.assertTrue(result["is_early_exit"])
        self.assertFalse(result["is_late"])
        self.assertAlmostEqual(result["early_minutes"], 15.0, places=1)
        self.assertAlmostEqual(result["hours"], 8.5 - 15.0 / 60.0, places=2)
        self.assertEqual(result["status"], "Present")

    def test_calc_overtime_after_shift_end_day(self):
        """After Shift End Time: hours past the shift's End Time are Day OT."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        shift = _day_shift(overtime_calculation_method="After Shift End Time")
        checkins = [
            _mk_checkin("C1", "2026-08-10 08:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 19:00:00", "OUT"),
        ]
        result = calc_overtime_hours(checkins, shift, total_hours=11.0)

        # 17:00-19:00 = 2h day OT, no night OT
        self.assertAlmostEqual(result["day_ot_hours"], 2.0, places=2)
        self.assertAlmostEqual(result["night_ot_hours"], 0.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 2.0, places=2)

    def test_calc_overtime_after_shift_end_no_double_count(self):
        """Late-night hours must not be counted in both Day and Night OT."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        shift = _day_shift(overtime_calculation_method="After Shift End Time")
        checkins = [
            _mk_checkin("C1", "2026-08-10 08:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 23:00:00", "OUT"),
        ]
        result = calc_overtime_hours(checkins, shift, total_hours=15.0)

        # 17:00-22:00 day OT = 5h; 22:00-23:00 night OT (default window) = 1h
        self.assertAlmostEqual(result["day_ot_hours"], 5.0, places=2)
        self.assertAlmostEqual(result["night_ot_hours"], 1.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 6.0, places=2)

    def test_calc_overtime_after_shift_end_night_shift(self):
        """Night OT uses the shift's Night OT Start/End window after standard hours."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        shift = _day_shift(
            is_night_shift=1,
            start_time="17:00:00",
            end_time="06:00:00",
            overtime_calculation_method="After Shift End Time",
            night_ot_start_time="01:00:00",
            night_ot_end_time="06:00:00",
        )
        checkins = [
            _mk_checkin("C1", "2026-08-10 17:00:00", "IN"),
            _mk_checkin("C2", "2026-08-11 06:00:00", "OUT"),
        ]
        result = calc_overtime_hours(checkins, shift, total_hours=13.0)

        # standard core 17:00-01:00; Night OT window 01:00-06:00 = 5h
        self.assertAlmostEqual(result["night_ot_hours"], 5.0, places=2)
        self.assertAlmostEqual(result["day_ot_hours"], 0.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 5.0, places=2)

    def test_overtime_threshold_minutes(self):
        """Total OT at or below the shift's threshold is discarded."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import calc_overtime_hours

        checkins = [
            _mk_checkin("C1", "2026-08-10 08:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 19:00:00", "OUT"),
        ]
        shift = _day_shift(overtime_calculation_method="After Shift End Time",
                           overtime_threshold_minutes=150)  # 2.5h threshold > 2h OT
        result = calc_overtime_hours(checkins, shift, total_hours=11.0)
        self.assertEqual(result["overtime_hours"], 0.0)
        self.assertEqual(result["day_ot_hours"], 0.0)

        shift = _day_shift(overtime_calculation_method="After Shift End Time",
                           overtime_threshold_minutes=60)  # 1h threshold < 2h OT
        result = calc_overtime_hours(checkins, shift, total_hours=11.0)
        self.assertAlmostEqual(result["overtime_hours"], 2.0, places=2)

    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_holidays_in_range")
    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_shift_for_employee")
    def test_process_employee_late_entry_with_after_shift_end_ot(self, mock_shift, mock_holidays):
        """End-to-end: grace deduction + shift-end OT roll up into the summary."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import process_employee

        mock_shift.return_value = _day_shift(
            late_entry_grace=10,
            overtime_calculation_method="After Shift End Time",
        )
        mock_holidays.return_value = set()

        checkins = [
            _mk_checkin("C1", "2026-08-10 09:00:00", "IN"),
            _mk_checkin("C2", "2026-08-10 19:00:00", "OUT"),
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

        # raw 10h, 50 min late (09:00 vs 08:10) -> 9.1667h; 2h day OT after 17:00
        self.assertEqual(result["working_days"], 1.0)
        self.assertAlmostEqual(result["total_working_hours"], 10.0 - 50.0 / 60.0, places=2)
        self.assertAlmostEqual(result["overtime_hours"], 2.0, places=2)
        self.assertAlmostEqual(result["day_ot_hours"], 2.0, places=2)
        self.assertIn("late entry", result["remarks"])


class TestNightShiftCrossMidnight(unittest.TestCase):
    """
    Night-shift checkins that cross midnight must be grouped as a single
    attendance period.  The OUT at shift-start is treated as the IN, and
    the IN at shift-end is treated as the OUT.
    """

    def test_night_shift_cross_midnight_grouping(self):
        """Checkins across midnight land in the same attendance day."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import (
            group_checkins_by_date,
        )

        shift = _day_shift(is_night_shift=1, start_time="17:00:00",
                           end_time="06:00:00")

        checkins = [
            _mk_checkin("C1", "2026-01-01 06:01:00", "IN"),
            _mk_checkin("C2", "2026-01-01 17:03:00", "OUT"),
            _mk_checkin("C3", "2026-01-02 06:02:00", "IN"),
            _mk_checkin("C4", "2026-01-02 17:04:00", "OUT"),
        ]

        daily = group_checkins_by_date(
            checkins, shift,
            from_date=date(2026, 1, 1), to_date=date(2026, 1, 2),
        )

        # 01/01 should contain the night-shift pair: 17:03 and next-day 06:02
        self.assertIn(date(2026, 1, 1), daily)
        day1 = sorted(daily[date(2026, 1, 1)], key=lambda c: c["time"])
        self.assertEqual(len(day1), 2)
        self.assertEqual(day1[0]["time"], datetime(2026, 1, 1, 17, 3))
        self.assertEqual(day1[1]["time"], datetime(2026, 1, 2, 6, 2))

        # Labels re-resolved: first punch = IN, last = OUT
        self.assertEqual(day1[0]["log_type"], "IN")
        self.assertEqual(day1[1]["log_type"], "OUT")

        # 02/01 should contain the next night-shift start
        self.assertIn(date(2026, 1, 2), daily)
        day2 = daily[date(2026, 1, 2)]
        self.assertEqual(len(day2), 1)
        self.assertEqual(day2[0]["time"], datetime(2026, 1, 2, 17, 4))

    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_holidays_in_range")
    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_shift_for_employee")
    def test_night_shift_hours_and_overtime(self, mock_shift, mock_holidays):
        """Cross-midnight hours and OT are calculated correctly."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import process_employee

        mock_shift.return_value = _day_shift(
            is_night_shift=1, start_time="17:00:00", end_time="06:00:00",
            overtime_calculation_method="After Shift End Time",
            night_ot_start_time="01:00:00",
            night_ot_end_time="06:00:00",
        )
        mock_holidays.return_value = set()

        checkins = [
            _mk_checkin("C1", "2026-01-01 06:01:00", "IN"),
            _mk_checkin("C2", "2026-01-01 17:03:00", "OUT"),
            _mk_checkin("C3", "2026-01-02 06:02:00", "IN"),
            _mk_checkin("C4", "2026-01-02 17:04:00", "OUT"),
        ]
        result = process_employee(
            employee="EMP-NIGHT",
            from_date="2026-01-01",
            to_date="2026-01-01",
            checkin_list=checkins,
            default_shift_name="Night Guard",
            doc_method="First IN - Last OUT",
            doc_missing_action="Mark as Invalid",
        )

        # 17:03 -> 06:02 = 12h 59min ≈ 12.98h total
        self.assertAlmostEqual(result["total_working_hours"],
                               12 + 59 / 60.0, places=1)
        self.assertEqual(result["working_days"], 1.0)

        # After Shift End Time: 17:03->01:00 regular, 01:00->06:02 night OT
        self.assertAlmostEqual(result["night_ot_hours"], 5.0, places=1)

    def test_night_shift_early_arrival_attributed_correctly(self):
        """An employee arriving 5 minutes early is still in the same shift."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import (
            group_checkins_by_date,
        )

        shift = _day_shift(is_night_shift=1, start_time="17:00:00",
                           end_time="06:00:00")
        checkins = [
            _mk_checkin("C1", "2026-01-01 16:55:00", "IN"),
            _mk_checkin("C2", "2026-01-02 06:02:00", "OUT"),
        ]
        daily = group_checkins_by_date(
            checkins, shift,
            from_date=date(2026, 1, 1), to_date=date(2026, 1, 2),
        )

        self.assertIn(date(2026, 1, 1), daily)
        day1 = sorted(daily[date(2026, 1, 1)], key=lambda c: c["time"])
        self.assertEqual(len(day1), 2)
        self.assertEqual(day1[0]["time"], datetime(2026, 1, 1, 16, 55))
        self.assertEqual(day1[1]["time"], datetime(2026, 1, 2, 6, 2))

    def test_night_shift_late_exit_included(self):
        """An employee leaving 30 minutes past shift end is still in the same shift."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import (
            group_checkins_by_date,
        )

        shift = _day_shift(is_night_shift=1, start_time="17:00:00",
                           end_time="06:00:00")
        checkins = [
            _mk_checkin("C1", "2026-01-01 17:00:00", "IN"),
            _mk_checkin("C2", "2026-01-02 06:30:00", "OUT"),
        ]
        daily = group_checkins_by_date(
            checkins, shift,
            from_date=date(2026, 1, 1), to_date=date(2026, 1, 2),
        )

        self.assertIn(date(2026, 1, 1), daily)
        day1 = sorted(daily[date(2026, 1, 1)], key=lambda c: c["time"])
        self.assertEqual(len(day1), 2)
        self.assertEqual(day1[1]["time"], datetime(2026, 1, 2, 6, 30))

    def test_night_shift_grace_period(self):
        """Late entry and early exit grace are computed across midnight."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import classify_day

        shift = _day_shift(
            is_night_shift=1, start_time="17:00:00", end_time="06:00:00",
            late_entry_grace=10, early_exit_grace=10,
        )
        checkins = [
            _mk_checkin("C1", "2026-01-01 17:20:00", "IN"),   # 10 min late beyond grace
            _mk_checkin("C2", "2026-01-02 05:45:00", "OUT"),  # 15 min early beyond grace
        ]
        result = classify_day(checkins, shift, "First IN - Last OUT",
                               "Mark as Invalid", work_date=date(2026, 1, 1))

        self.assertTrue(result["is_late"])
        self.assertTrue(result["is_early_exit"])
        self.assertAlmostEqual(result["late_minutes"], 10.0, places=1)
        self.assertAlmostEqual(result["early_minutes"], 5.0, places=1)

    def test_night_shift_does_not_pair_with_next_day(self):
        """The OUT punch at 17:04 on Day 2 is NOT consumed by Day 1's shift."""
        from zkteco_attendance.zkteco_attendance.attendance_processor import (
            group_checkins_by_date,
        )

        shift = _day_shift(is_night_shift=1, start_time="17:00:00",
                           end_time="06:00:00")
        checkins = [
            _mk_checkin("C1", "2026-01-01 17:00:00", "IN"),
            _mk_checkin("C2", "2026-01-02 06:00:00", "OUT"),
            _mk_checkin("C3", "2026-01-02 17:00:00", "IN"),
            _mk_checkin("C4", "2026-01-03 06:00:00", "OUT"),
        ]
        daily = group_checkins_by_date(
            checkins, shift,
            from_date=date(2026, 1, 1), to_date=date(2026, 1, 3),
        )

        # Day 1: 17:00 on 01/01 + 06:00 on 01/02
        day1 = sorted(daily.get(date(2026, 1, 1), []), key=lambda c: c["time"])
        self.assertEqual(len(day1), 2)
        self.assertEqual(day1[0]["time"], datetime(2026, 1, 1, 17, 0))
        self.assertEqual(day1[1]["time"], datetime(2026, 1, 2, 6, 0))

        # Day 2: 17:00 on 01/02 + 06:00 on 01/03
        day2 = sorted(daily.get(date(2026, 1, 2), []), key=lambda c: c["time"])
        self.assertEqual(len(day2), 2)
        self.assertEqual(day2[0]["time"], datetime(2026, 1, 2, 17, 0))
        self.assertEqual(day2[1]["time"], datetime(2026, 1, 3, 6, 0))


class TestNightShiftAcceptance(unittest.TestCase):
    """
    Exact acceptance test from the user's specification.
    """

    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_holidays_in_range")
    @patch("zkteco_attendance.zkteco_attendance.attendance_processor.get_shift_for_employee")
    def test_user_acceptance_test(self, mock_shift, mock_holidays):
        """
        Check-ins:
          01/01 06:01 IN, 01/01 17:03 OUT
          02/01 06:02 IN, 02/01 17:04 OUT
        Shift: 17:00 -> 06:00
        Expected for 01/01:
          IN  = 01/01 17:03
          OUT = 02/01 06:02
          Regular  = 17:03 -> 01:00 ≈ 8h
          Night OT = 01:00 -> 06:02 ≈ 5h
        """
        from zkteco_attendance.zkteco_attendance.attendance_processor import process_employee

        mock_shift.return_value = _day_shift(
            is_night_shift=1,
            start_time="17:00:00",
            end_time="06:00:00",
            standard_working_hours=8,
            overtime_calculation_method="After Shift End Time",
            night_ot_start_time="01:00:00",
            night_ot_end_time="06:00:00",
        )
        mock_holidays.return_value = set()

        checkins = [
            _mk_checkin("C1", "2026-01-01 06:01:00", "IN"),
            _mk_checkin("C2", "2026-01-01 17:03:00", "OUT"),
            _mk_checkin("C3", "2026-01-02 06:02:00", "IN"),
            _mk_checkin("C4", "2026-01-02 17:04:00", "OUT"),
        ]

        result = process_employee(
            employee="EMP-NIGHT",
            from_date="2026-01-01",
            to_date="2026-01-01",
            checkin_list=checkins,
            default_shift_name="Night Guard",
            doc_method="First IN - Last OUT",
            doc_missing_action="Mark as Invalid",
        )

        # 17:03 -> 06:02 = 12h 59min ≈ 12.98h
        self.assertAlmostEqual(result["total_working_hours"],
                               12 + 59 / 60.0, places=1)
        self.assertEqual(result["working_days"], 1.0)

        # Night OT: 01:00 -> 06:02 = 5h 2min ≈ 5.03h
        self.assertAlmostEqual(result["night_ot_hours"], 5.0, places=0)


if __name__ == "__main__":
    unittest.main()
