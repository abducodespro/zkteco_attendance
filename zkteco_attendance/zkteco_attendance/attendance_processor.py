"""
Attendance Processor
====================
Core logic for Attendance Summary processing.

Handles:
- Working day calculation (Mon-Sat by default)
- Employee Checkin grouping by date
- Night shift date attribution
- First IN/Last OUT vs Actual Pairs methods
- Present / Half-Day / Absent classification
- Missing checkin scenarios
- Absent hours calculation
- Overtime calculation split into four explicit categories:
    Day OT      - 06:00 to 22:00 on regular working days, for hours beyond the daily limit
    Night OT    - 22:00 to 06:00 (next day) on regular working days
    Weekend OT  - 00:00 to 24:00 on the weekly rest day (Sunday)
    Holiday OT  - 00:00 to 24:00 on official public holidays (Holiday List)
"""

import frappe
from frappe import _
from frappe.utils import getdate, get_datetime, nowdate, flt
from datetime import date, datetime, timedelta, time
from zkteco_attendance.zkteco_attendance.utils import has_column


# ─────────────────────────────────────────────────────────────────────────────
# Overtime time windows (fixed policy)
# ─────────────────────────────────────────────────────────────────────────────

DAY_OT_START    = time(6, 0)    # 06:00
DAY_OT_END      = time(22, 0)   # 22:00
NIGHT_OT_START  = time(22, 0)   # 22:00
NIGHT_OT_END    = time(6, 0)    # 06:00 (next day)


# ─────────────────────────────────────────────────────────────────────────────
# Holidays (public holidays from the Holiday List doctype)
# ─────────────────────────────────────────────────────────────────────────────

def get_holiday_list_for_employee(employee):
    """
    Return the Holiday List name for an employee.
    Uses Employee.holiday_list, falling back to the Company default.
    Returns None when no Holiday List is configured.
    """
    holiday_list = None
    try:
        holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    except Exception:
        holiday_list = None
    if not holiday_list:
        try:
            company = frappe.db.get_value("Employee", employee, "company")
        except Exception:
            company = None
        if company:
            try:
                holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
            except Exception:
                holiday_list = None
    return holiday_list


def get_holidays_in_range(employee, from_date, to_date):
    """
    Return a set of dates that are official public holidays for the employee
    within [from_date, to_date].

    Weekly-off entries in the Holiday child table (weekly_off = 1) are
    excluded — only true public holidays count as holiday overtime.
    """
    holiday_list = get_holiday_list_for_employee(employee)
    if not holiday_list:
        return set()
    if not frappe.db.table_exists("Holiday"):
        return set()

    filters = {
        "parent": holiday_list,
        "holiday_date": ["between", [str(from_date), str(to_date)]],
    }
    if has_column("Holiday", "weekly_off"):
        filters["weekly_off"] = 0

    rows = frappe.db.get_all(
        "Holiday",
        filters=filters,
        fields=["holiday_date"],
    )
    return {getdate(r.holiday_date) for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# Working Days
# ─────────────────────────────────────────────────────────────────────────────

def get_working_days_in_range(from_date, to_date, saturday_mode="Full Day"):
    """
    Return list of date objects that are working days.
    Sundays are always excluded.
    Saturday behaviour is controlled by saturday_mode:
      'Full Day'  — Saturday counts as a full working day (default)
      'Half Day'  — Saturday is included but classified as a half day
      'Off'       — Saturday is excluded entirely
    """
    from_date = getdate(from_date)
    to_date   = getdate(to_date)
    days = []
    current = from_date
    while current <= to_date:
        wd = current.weekday()  # 0=Mon … 5=Sat, 6=Sun
        if wd == 6:  # Sunday — always off
            current += timedelta(days=1)
            continue
        if wd == 5 and saturday_mode == "Off":  # Saturday excluded
            current += timedelta(days=1)
            continue
        days.append(current)
        current += timedelta(days=1)
    return days


def count_working_days(from_date, to_date):
    return len(get_working_days_in_range(from_date, to_date))


# ─────────────────────────────────────────────────────────────────────────────
# Shift lookup for an employee
# ─────────────────────────────────────────────────────────────────────────────

SHIFT_FIELDS = [
    "name", "start_time", "end_time", "is_night_shift",
    "full_day_hours", "half_day_hours", "standard_working_hours",
    "working_hours_method", "missing_checkin_action",
    "late_entry_grace", "early_exit_grace",
    "saturday_mode", "saturday_half_day_hours",
    "enable_overtime", "overtime_calculation_method",
    "overtime_threshold_minutes",
    "max_overtime_hours_per_day",
    "standard_start_time", "night_ot_start_time", "night_ot_end_time",
]


def get_shift_for_employee(employee, work_date, default_shift_name=None):
    """
    Return a ZK Shift Type doc (as dict) for employee on a given date, or None.
    Checks ZK Shift Assignment first, then falls back to default_shift_name.
    """
    work_date_str = str(work_date)
    columns = ", ".join("st.{0}".format(f) for f in SHIFT_FIELDS)

    result = frappe.db.sql("""
        SELECT {columns}
        FROM `tabZK Shift Assignment` sa
        JOIN `tabZK Shift Assignment Employee` sae ON sae.parent = sa.name
        JOIN `tabZK Shift Type` st ON st.name = sa.shift_type
        WHERE sae.employee = %s
          AND sa.status = 'Active'
          AND sa.from_date <= %s
          AND sa.to_date   >= %s
        ORDER BY sa.from_date DESC
        LIMIT 1
    """.format(columns=columns), (employee, work_date_str, work_date_str), as_dict=True)

    if result:
        return result[0]

    if default_shift_name:
        shift = frappe.db.get_value(
            "ZK Shift Type", default_shift_name,
            SHIFT_FIELDS,
            as_dict=True
        )
        return shift

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Fetch and group checkins
# ─────────────────────────────────────────────────────────────────────────────

def fetch_checkins(employee_list, from_date, to_date):
    """
    Fetch all Employee Checkin records for the given employees and period.
    Returns dict: { employee -> [ {name, time, log_type, is_overtime,
                                   manually_edited, edited_by, edited_at}, ... ] }
    """
    from_dt   = str(from_date) + " 00:00:00"
    to_dt_ext = str(getdate(to_date) + timedelta(days=1)) + " 23:59:59"

    if not employee_list:
        return {}

    has_overtime_col      = has_column("Employee Checkin", "is_overtime")
    has_manual_edited_col = has_column("Employee Checkin", "manually_edited")

    extra_select = ""
    if has_overtime_col:
        extra_select += ", is_overtime"
    if has_manual_edited_col:
        extra_select += ", manually_edited, edited_by, edited_at"

    placeholders = ", ".join(["%s"] * len(employee_list))
    rows = frappe.db.sql("""
        SELECT name, employee, time, log_type{extra}
        FROM `tabEmployee Checkin`
        WHERE employee IN ({placeholders})
          AND time BETWEEN %s AND %s
        ORDER BY employee, time
    """.format(placeholders=placeholders, extra=extra_select),
        tuple(employee_list) + (from_dt, to_dt_ext),
        as_dict=True
    )

    grouped = {}
    for r in rows:
        grouped.setdefault(r.employee, []).append({
            "name":           r.name,
            "time":           get_datetime(r.time),
            "log_type":       r.log_type,
            "is_overtime":    bool(r.get("is_overtime")) if has_overtime_col else False,
            "manually_edited": bool(r.get("manually_edited")) if has_manual_edited_col else False,
            "edited_by":      r.get("edited_by") or "",
            "edited_at":      str(r.get("edited_at") or ""),
        })
    return grouped


def group_checkins_by_date(checkins, shift, default_method="First IN - Last OUT",
                            from_date=None, to_date=None):
    """
    Group a flat list of checkin dicts by attendance date.
    Night shift logic: if shift is_night_shift, a checkout in the AM
    belongs to the previous calendar day's shift.
    Returns dict: { date -> [checkin, ...] }
    """
    from_date = getdate(from_date) if from_date else None
    to_date   = getdate(to_date)   if to_date   else None

    daily = {}
    for c in checkins:
        dt = c["time"]
        att_date = dt.date()

        if shift and shift.get("is_night_shift"):
            # Checkins in early AM (before shift end) belong to previous date
            end_str = str(shift.get("end_time") or "06:00:00")
            end_t   = _coerce_time(end_str)
            if dt.time() <= end_t:
                att_date = (dt - timedelta(days=1)).date()

        # Only include dates within our target range
        if from_date and att_date < from_date:
            continue
        if to_date and att_date > to_date:
            continue

        daily.setdefault(att_date, []).append(c)

    return daily


def _coerce_time(value):
    """Parse a Time-field value (str, timedelta, or time) into datetime.time."""
    if isinstance(value, str):
        # Frappe Time fields commonly come back as "HH:MM:SS" or "HH:MM:SS.ffffff"
        value = value.split(".")[0]
        return datetime.strptime(value, "%H:%M:%S").time()
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds()) % (24 * 3600)
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return datetime(2000, 1, 1, h, m, s).time()
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Working hours calculation
# ─────────────────────────────────────────────────────────────────────────────

def calc_hours_first_last(day_checkins):
    """Method 1: Last checkout minus first checkin (total span)."""
    if not day_checkins:
        return 0.0
    times = sorted(c["time"] for c in day_checkins)
    delta = times[-1] - times[0]
    return delta.total_seconds() / 3600


def calc_hours_actual_pairs(day_checkins):
    """
    Method 2: Sum of each IN->OUT pair.
    Unmatched IN at end is ignored.
    """
    sorted_ci = sorted(day_checkins, key=lambda c: c["time"])
    total = 0.0
    i = 0
    while i < len(sorted_ci) - 1:
        if sorted_ci[i]["log_type"] == "IN" and sorted_ci[i+1]["log_type"] == "OUT":
            delta = sorted_ci[i+1]["time"] - sorted_ci[i]["time"]
            total += delta.total_seconds() / 3600
            i += 2
        else:
            i += 1
    return total


def calc_working_hours(day_checkins, method="First IN - Last OUT"):
    if method == "Actual Pairs (IN-OUT)":
        return calc_hours_actual_pairs(day_checkins)
    return calc_hours_first_last(day_checkins)


# ─────────────────────────────────────────────────────────────────────────────
# Overtime calculation
# ─────────────────────────────────────────────────────────────────────────────

def _worked_intervals(day_checkins, method):
    """
    Return the worked time intervals as a list of (start, end) datetimes,
    following the same rules as calc_working_hours (First IN - Last OUT
    or Actual Pairs).
    """
    sorted_ci = sorted(day_checkins, key=lambda c: c["time"])
    if method == "Actual Pairs (IN-OUT)":
        intervals = []
        i = 0
        while i < len(sorted_ci) - 1:
            if sorted_ci[i]["log_type"] == "IN" and sorted_ci[i + 1]["log_type"] == "OUT":
                intervals.append((sorted_ci[i]["time"], sorted_ci[i + 1]["time"]))
                i += 2
            else:
                i += 1
        return intervals
    if not sorted_ci:
        return []
    return [(sorted_ci[0]["time"], sorted_ci[-1]["time"])]


def _overlap_hours(start, end, win_start, win_end):
    """Hours of overlap between a worked interval [start, end] and a window."""
    return max(0.0, (min(end, win_end) - max(start, win_start)).total_seconds() / 3600)


def _window_hours(intervals, start_t, end_t):
    """
    Sum of worked hours that fall inside the recurring daily clock window
    [start_t, end_t]. Windows that cross midnight (start_t > end_t) are
    handled by anchoring the window on the interval start date and, when
    the interval spills past midnight, again on the interval end date.
    """
    crosses = start_t > end_t
    total = 0.0
    for start, end in intervals:
        d0 = start.date()
        if crosses:
            ws = datetime.combine(d0, start_t)
            we = datetime.combine(d0 + timedelta(days=1), end_t)
        else:
            ws = datetime.combine(d0, start_t)
            we = datetime.combine(d0, end_t)
        total += _overlap_hours(start, end, ws, we)

        # Interval crosses midnight — also anchor the window on the end date
        if end.date() > d0:
            d1 = end.date()
            if crosses:
                ws = datetime.combine(d1, start_t)
                we = datetime.combine(d1 + timedelta(days=1), end_t)
            else:
                ws = datetime.combine(d1, start_t)
                we = datetime.combine(d1, end_t)
            total += _overlap_hours(start, end, ws, we)
    return total


def calc_overtime_hours(day_checkins, shift, total_hours, day_type="working",
                        method="First IN - Last OUT"):
    """
    Calculate overtime hours for one day, split into four explicit categories:
      {
        overtime_hours:   total overtime hours,
        day_ot_hours:     hours in 06:00-22:00 on working days beyond the daily limit,
        night_ot_hours:   hours in 22:00-06:00 (next day) on working days,
        weekend_ot_hours: hours worked on the weekly rest day (Sunday),
        holiday_ot_hours: hours worked on official public holidays,
      }
    Returns the zeros dict if overtime is disabled on the shift.

    day_type is one of "working" | "weekend" | "holiday":
      - working: Day OT = day-window hours (06:00-22:00) beyond the daily limit
                 (standard_working_hours, default 8); Night OT = all night-window
                 hours (22:00-06:00 next day).
      - weekend: every hour worked counts as weekend OT (00:00-24:00).
      - holiday: every hour worked counts as holiday OT (00:00-24:00).
    """
    zero = {"overtime_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0,
            "weekend_ot_hours": 0.0, "holiday_ot_hours": 0.0}
    if not shift or not shift.get("enable_overtime"):
        return zero
    if not day_checkins:
        return zero

    std_hours       = flt(shift.get("standard_working_hours") or 8)
    threshold_hours = flt(shift.get("overtime_threshold_minutes") or 0) / 60.0
    max_ot          = flt(shift.get("max_overtime_hours_per_day") or 0)

    day_ot = night_ot = weekend_ot = holiday_ot = 0.0

    if day_type == "holiday":
        holiday_ot = total_hours
    elif day_type == "weekend":
        weekend_ot = total_hours
    else:
        intervals = _worked_intervals(day_checkins, method)
        day_win   = _window_hours(intervals, DAY_OT_START, DAY_OT_END)
        night_win = _window_hours(intervals, NIGHT_OT_START, NIGHT_OT_END)
        day_ot    = max(0.0, day_win - std_hours)
        night_ot  = night_win

    total_ot = day_ot + night_ot + weekend_ot + holiday_ot

    # Apply threshold
    if total_ot <= threshold_hours:
        return zero

    # Apply daily cap (proportionally across categories)
    if max_ot and total_ot > max_ot:
        scale = max_ot / total_ot
        day_ot     *= scale
        night_ot   *= scale
        weekend_ot *= scale
        holiday_ot *= scale
        total_ot    = max_ot

    return {
        "overtime_hours":   round(total_ot, 2),
        "day_ot_hours":     round(day_ot,   2),
        "night_ot_hours":   round(night_ot, 2),
        "weekend_ot_hours": round(weekend_ot, 2),
        "holiday_ot_hours": round(holiday_ot, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Daily status classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_day(day_checkins, shift, doc_method, doc_missing_action,
                 is_saturday=False, day_type="working"):
    """
    Returns a dict with attendance status, hours, and overtime breakdown.
    When is_saturday=True, applies Saturday-specific hour thresholds.

    day_type is one of "working" | "weekend" | "holiday":
      - weekend (Sunday weekly rest day): status is "Weekly Off" when no
        checkins, "Present" when worked (all hours = weekend OT).
      - holiday (public holiday): status is "Holiday" when no checkins,
        "Present" when worked (all hours = holiday OT).
    """
    full_hours = flt(shift.get("full_day_hours") or 8)
    half_hours = flt(shift.get("half_day_hours") or 4)
    std_hours  = flt(shift.get("standard_working_hours") or 8)
    method     = doc_method or shift.get("working_hours_method") or "First IN - Last OUT"
    missing    = doc_missing_action or shift.get("missing_checkin_action") or "Mark as Invalid"

    # Saturday overrides
    saturday_mode = shift.get("saturday_mode") or "Full Day"
    if is_saturday and saturday_mode == "Half Day":
        sat_min = flt(shift.get("saturday_half_day_hours") or 4)
        # Saturday half-day: if any hours present → half day regardless of hours
        full_hours = sat_min   # treat sat_min hours as "full" for Saturday
        half_hours = 0.1       # any attendance counts as half day
        std_hours  = std_hours / 2

    empty_ot = {"overtime_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0,
                "weekend_ot_hours": 0.0, "holiday_ot_hours": 0.0}

    # No checkins at all
    if not day_checkins:
        if day_type == "holiday":
            return {"status": "Holiday", "hours": 0.0, "absent_hours": 0.0, **empty_ot}
        if day_type == "weekend":
            return {"status": "Weekly Off", "hours": 0.0, "absent_hours": 0.0, **empty_ot}
        return {"status": "Absent", "hours": 0.0, "absent_hours": std_hours, **empty_ot}

    has_in  = any(c["log_type"] == "IN"  for c in day_checkins)
    has_out = any(c["log_type"] == "OUT" for c in day_checkins)

    if not (has_in and has_out):
        if missing == "Mark as Present":
            hours = calc_working_hours(day_checkins, method)
            ot = calc_overtime_hours(day_checkins, shift, hours,
                                     day_type=day_type, method=method)
            return {"status": "Present", "hours": hours, "absent_hours": 0.0, **ot}
        elif missing == "Require Manual Review":
            return {"status": "Manual Review", "hours": 0.0, "absent_hours": 0.0, **empty_ot}
        else:
            return {"status": "Invalid", "hours": 0.0, "absent_hours": 0.0, **empty_ot}

    hours = calc_working_hours(day_checkins, method)
    ot    = calc_overtime_hours(day_checkins, shift, hours, day_type=day_type, method=method)

    # Weekly rest day / public holiday worked — every hour is OT
    if day_type == "holiday":
        return {"status": "Present", "hours": hours, "absent_hours": 0.0, **ot}
    if day_type == "weekend":
        return {"status": "Present", "hours": hours, "absent_hours": 0.0, **ot}

    if is_saturday and saturday_mode == "Half Day":
        # Saturday with any attendance → half day, no absent hours
        return {"status": "Half Day", "hours": hours, "absent_hours": 0.0, **ot}

    if hours >= full_hours:
        return {"status": "Present", "hours": hours, "absent_hours": 0.0, **ot}
    elif hours >= half_hours:
        return {"status": "Half Day", "hours": hours, "absent_hours": std_hours / 2, **ot}
    else:
        return {"status": "Absent", "hours": hours, "absent_hours": std_hours, **ot}


# ─────────────────────────────────────────────────────────────────────────────
# Per-employee calculation
# ─────────────────────────────────────────────────────────────────────────────

def process_employee(employee, from_date, to_date,
                     checkin_list, default_shift_name,
                     doc_method, doc_missing_action):
    from_date = getdate(from_date)
    to_date   = getdate(to_date)

    shift = get_shift_for_employee(employee, from_date, default_shift_name)
    saturday_mode = (shift.get("saturday_mode") or "Full Day") if shift else "Full Day"
    holidays = get_holidays_in_range(employee, from_date, to_date)

    daily_checkins = group_checkins_by_date(
        checkin_list, shift,
        default_method=doc_method,
        from_date=from_date, to_date=to_date
    )

    working_days       = 0.0
    absent_days        = 0.0
    half_days          = 0.0
    total_hours        = 0.0
    absent_hours       = 0.0
    overtime_hours     = 0.0
    day_ot_hours       = 0.0
    night_ot_hours     = 0.0
    weekend_ot_hours   = 0.0
    holiday_ot_hours   = 0.0
    overtime_days      = 0
    invalid_days       = 0
    manual_review_days = 0
    remarks_list       = []

    current = from_date
    while current <= to_date:
        work_date    = current
        day_shift    = get_shift_for_employee(employee, work_date, default_shift_name) or shift
        day_checkins = daily_checkins.get(work_date, [])
        is_saturday  = (work_date.weekday() == 5)

        if work_date in holidays:
            day_type = "holiday"
        elif work_date.weekday() == 6:
            day_type = "weekend"
        elif is_saturday and saturday_mode == "Off":
            current += timedelta(days=1)
            continue
        else:
            day_type = "working"

        result = classify_day(day_checkins, day_shift or {}, doc_method, doc_missing_action,
                               is_saturday=is_saturday, day_type=day_type)

        total_hours    += result["hours"]
        absent_hours   += result["absent_hours"]
        overtime_hours += result.get("overtime_hours", 0.0)
        day_ot_hours   += result.get("day_ot_hours", 0.0)
        night_ot_hours += result.get("night_ot_hours", 0.0)
        weekend_ot_hours += result.get("weekend_ot_hours", 0.0)
        holiday_ot_hours += result.get("holiday_ot_hours", 0.0)

        if result.get("overtime_hours", 0.0) > 0:
            overtime_days += 1

        if day_type != "working":
            # Weekly rest days and public holidays never count toward
            # working days / absent days — only hours and OT are recorded.
            current += timedelta(days=1)
            continue

        if result["status"] == "Present":
            working_days += 1.0
        elif result["status"] == "Half Day":
            working_days += 0.5
            absent_days  += 0.5
            half_days    += 1
        elif result["status"] == "Absent":
            absent_days  += 1.0
        elif result["status"] == "Invalid":
            invalid_days += 1
            remarks_list.append("{}: invalid checkin".format(work_date))
        elif result["status"] == "Manual Review":
            manual_review_days += 1
            remarks_list.append("{}: needs review".format(work_date))

        current += timedelta(days=1)

    return {
        "working_days":        round(working_days, 1),
        "absent_days":         round(absent_days, 1),
        "half_days":           half_days,
        "total_working_hours": round(total_hours, 2),
        "absent_hours":        round(absent_hours, 2),
        "overtime_hours":      round(overtime_hours, 2),
        "day_ot_hours":        round(day_ot_hours, 2),
        "night_ot_hours":      round(night_ot_hours, 2),
        "weekend_ot_hours":    round(weekend_ot_hours, 2),
        "holiday_ot_hours":    round(holiday_ot_hours, 2),
        "overtime_days":       overtime_days,
        "invalid_days":        invalid_days,
        "manual_review_days":  manual_review_days,
        "remarks":             ", ".join(remarks_list[:5]) if remarks_list else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-employee, per-day breakdown (for the Daily Checkins dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def get_employee_daily_breakdown(employee, from_date, to_date,
                                  checkin_list, default_shift_name,
                                  doc_method, doc_missing_action):
    from_date = getdate(from_date)
    to_date   = getdate(to_date)

    shift = get_shift_for_employee(employee, from_date, default_shift_name)
    saturday_mode = (shift.get("saturday_mode") or "Full Day") if shift else "Full Day"
    holidays = get_holidays_in_range(employee, from_date, to_date)

    daily_checkins = group_checkins_by_date(
        checkin_list, shift,
        default_method=doc_method,
        from_date=from_date, to_date=to_date
    )

    breakdown = []
    current = from_date
    while current <= to_date:
        work_date    = current
        day_shift    = get_shift_for_employee(employee, work_date, default_shift_name) or shift or {}
        day_checkins = sorted(daily_checkins.get(work_date, []), key=lambda c: c["time"])
        is_saturday  = (work_date.weekday() == 5)

        if work_date in holidays:
            day_type = "holiday"
        elif work_date.weekday() == 6:
            day_type = "weekend"
        elif is_saturday and saturday_mode == "Off":
            current += timedelta(days=1)
            continue
        else:
            day_type = "working"

        result = classify_day(day_checkins, day_shift, doc_method, doc_missing_action,
                               is_saturday=is_saturday, day_type=day_type)

        breakdown.append({
            "date":             str(work_date),
            "weekday":          work_date.strftime("%A"),
            "is_saturday":      is_saturday,
            "is_weekend":       day_type == "weekend",
            "is_holiday":       day_type == "holiday",
            "status":           result["status"],
            "hours":            result["hours"],
            "overtime_hours":   result.get("overtime_hours", 0.0),
            "day_ot_hours":     result.get("day_ot_hours", 0.0),
            "night_ot_hours":   result.get("night_ot_hours", 0.0),
            "weekend_ot_hours": result.get("weekend_ot_hours", 0.0),
            "holiday_ot_hours": result.get("holiday_ot_hours", 0.0),
            "checkins": [
                {
                    "name":           c.get("name") or "",
                    "time":           c["time"].strftime("%H:%M:%S"),
                    "log_type":       c["log_type"],
                    "is_overtime":    bool(c.get("is_overtime")),
                    "manually_edited": bool(c.get("manually_edited")),
                    "edited_by":      c.get("edited_by") or "",
                    "edited_at":      c.get("edited_at") or "",
                }
                for c in day_checkins
            ],
        })

        current += timedelta(days=1)

    return breakdown


def get_daily_checkins_data(attendance_summary=None, from_date=None, to_date=None,
                            employee_list=None, company=None):
    """
    Build the full payload for the Daily Checkins dashboard.

    Can be driven by an Attendance Summary (which provides from_date,
    to_date, employees, and processing settings) OR by a direct date range
    + employee list (for standalone use where no summary exists yet).
    """
    if attendance_summary:
        doc = frappe.get_doc("Attendance Summary", attendance_summary)
        from_date      = str(doc.from_date)
        to_date        = str(doc.to_date)
        employee_list  = [row.employee for row in doc.details]
        company        = doc.company
        doc_method     = doc.working_hours_method
        doc_missing    = doc.missing_checkin_action
        default_shift  = doc.shift_type
    else:
        doc_method    = "First IN - Last OUT"
        doc_missing   = "Mark as Invalid"
        default_shift = None

    if not employee_list:
        # Standalone mode (no Attendance Summary): auto-fetch employees that
        # are mapped to a biometric device (attendance_device_id AND
        # zk_biometric_device set), so the page works without a summary.
        if not attendance_summary:
            # "is set" excludes both empty strings and NULL in Frappe
            filters = {
                "status": "Active",
                "attendance_device_id": ["is", "set"],
                "zk_biometric_device": ["is", "set"],
            }
            if company:
                filters["company"] = company
            employee_list = [
                e["name"]
                for e in frappe.get_all("Employee", filters=filters, fields=["name"])
            ]

        if not employee_list:
            return {
                "attendance_summary": attendance_summary or "",
                "company": company or "",
                "from_date": from_date or "",
                "to_date": to_date or "",
                "employees": [],
            }

    checkins_by_employee = fetch_checkins(employee_list, from_date, to_date)

    # Resolve employee names for standalone mode
    emp_info = {}
    if not attendance_summary and employee_list:
        rows = frappe.get_all("Employee",
                              filters={"name": ["in", employee_list]},
                              fields=["name", "employee_name", "department", "designation"])
        emp_info = {r.name: r for r in rows}

    employees = []
    for emp_id in employee_list:
        emp_checkins = checkins_by_employee.get(emp_id, [])

        # Get name/dept info from summary row or direct lookup
        if attendance_summary:
            row = next((r for r in doc.details if r.employee == emp_id), None)
            emp_name  = row.employee_name if row else emp_id
            dept      = row.department if row else ""
            desig     = row.designation if row else ""
        else:
            info = emp_info.get(emp_id, {})
            emp_name = info.get("employee_name") or emp_id
            dept     = info.get("department") or ""
            desig    = info.get("designation") or ""

        days = get_employee_daily_breakdown(
            employee=emp_id,
            from_date=from_date,
            to_date=to_date,
            checkin_list=emp_checkins,
            default_shift_name=default_shift,
            doc_method=doc_method,
            doc_missing_action=doc_missing,
        )
        employees.append({
            "employee":      emp_id,
            "employee_name": emp_name,
            "department":    dept,
            "designation":   desig,
            "days":          days,
        })

    return {
        "attendance_summary": attendance_summary or "",
        "company":    company or "",
        "from_date":  from_date,
        "to_date":    to_date,
        "employees":  employees,
    }


def save_manual_checkin_record(employee, checkin_time, log_type, checkin_name=None):
    """
    Create or update an Employee Checkin manually, without needing an
    Attendance Summary (standalone Daily Checkins mode).

    Records edited_by / edited_at / manually_edited flags.
    Returns {"name": ..., "action": "created" | "updated"}.
    """
    from frappe.utils import now_datetime as _now

    if not employee or not checkin_time or not log_type:
        frappe.throw(_("Employee, Check-in Time, and Log Type are required."))

    editor = frappe.session.user
    now    = _now()

    if checkin_name and frappe.db.exists("Employee Checkin", checkin_name):
        # Update existing
        doc = frappe.get_doc("Employee Checkin", checkin_name)
        doc.time            = checkin_time
        doc.log_type        = log_type
        doc.manually_edited = 1
        doc.edited_by       = editor
        doc.edited_at       = now
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"name": doc.name, "action": "updated"}
    else:
        # Create new
        emp_doc = frappe.db.get_value("Employee", employee, ["employee_name"], as_dict=True)
        doc = frappe.get_doc({
            "doctype":        "Employee Checkin",
            "employee":       employee,
            "employee_name":  emp_doc.employee_name if emp_doc else employee,
            "time":           checkin_time,
            "log_type":       log_type,
            "manually_edited": 1,
            "edited_by":      editor,
            "edited_at":      now,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"name": doc.name, "action": "created"}
