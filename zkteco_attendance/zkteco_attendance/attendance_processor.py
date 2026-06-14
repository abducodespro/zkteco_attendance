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
- Overtime calculation (After Standard Hours / After Shift End Time / OT Punches Only)
"""

import frappe
from frappe import _
from frappe.utils import getdate, get_datetime, nowdate, flt
from datetime import date, datetime, timedelta
from zkteco_attendance.zkteco_attendance.utils import has_column


# ─────────────────────────────────────────────────────────────────────────────
# Working Days
# ─────────────────────────────────────────────────────────────────────────────

def get_working_days_in_range(from_date, to_date):
    """
    Return list of date objects that are working days (Mon-Sat by default).
    Excludes Sundays. Future: hook into Holiday List.
    """
    from_date = getdate(from_date)
    to_date   = getdate(to_date)
    days = []
    current = from_date
    while current <= to_date:
        if current.weekday() != 6:   # 6 = Sunday
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
    "enable_overtime", "overtime_calculation_method",
    "overtime_threshold_minutes", "overtime_rate_multiplier",
    "max_overtime_hours_per_day",
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
    Returns dict: { employee -> [ {time, log_type, is_overtime}, ... ] }
    """
    from_dt = str(from_date) + " 00:00:00"
    # Extend to_date by 1 day to capture night shift checkouts
    to_dt_ext = str(getdate(to_date) + timedelta(days=1)) + " 23:59:59"

    if not employee_list:
        return {}

    # `is_overtime` may not exist on very old installs that haven't run the
    # v1_1 patch yet — fall back gracefully.
    has_overtime_col = has_column("Employee Checkin", "is_overtime")
    overtime_select = ", is_overtime" if has_overtime_col else ""

    placeholders = ", ".join(["%s"] * len(employee_list))
    rows = frappe.db.sql("""
        SELECT employee, time, log_type{overtime_select}
        FROM `tabEmployee Checkin`
        WHERE employee IN ({placeholders})
          AND time BETWEEN %s AND %s
        ORDER BY employee, time
    """.format(placeholders=placeholders, overtime_select=overtime_select),
        tuple(employee_list) + (from_dt, to_dt_ext),
        as_dict=True
    )

    grouped = {}
    for r in rows:
        grouped.setdefault(r.employee, []).append({
            "time":        get_datetime(r.time),
            "log_type":    r.log_type,
            "is_overtime": bool(r.get("is_overtime")) if has_overtime_col else False,
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

def calc_overtime_hours(day_checkins, shift, total_hours):
    """
    Calculate overtime hours for one day based on the shift's overtime
    configuration. Returns 0.0 if overtime is not enabled for the shift.

    Methods:
    - "After Standard Hours": OT = max(0, total_hours - standard_working_hours)
    - "After Shift End Time": OT = time worked between the shift's End Time
       and the last OUT punch of the day (if the employee stayed past
       shift end).
    - "OT Punches Only": OT = sum of duration between explicit OT-In /
       OT-Out checkin pairs (is_overtime flag set on the Employee Checkin).

    A configurable threshold (in minutes) is subtracted before any OT is
    counted, to avoid paying overtime for minor rounding/lateness in
    leaving. An optional daily cap can also be applied.
    """
    if not shift or not shift.get("enable_overtime"):
        return 0.0

    method = shift.get("overtime_calculation_method") or "After Standard Hours"
    threshold_minutes = flt(shift.get("overtime_threshold_minutes") or 0)
    threshold_hours = threshold_minutes / 60.0
    max_ot = flt(shift.get("max_overtime_hours_per_day") or 0)

    ot_hours = 0.0

    if method == "OT Punches Only":
        ot_checkins = [c for c in day_checkins if c.get("is_overtime")]
        ot_hours = calc_hours_actual_pairs(ot_checkins)

    elif method == "After Shift End Time":
        end_str = shift.get("end_time")
        if not end_str or not day_checkins:
            ot_hours = 0.0
        else:
            end_t = _coerce_time(end_str)
            outs = [c["time"] for c in day_checkins if c["log_type"] == "OUT"]
            if not outs:
                ot_hours = 0.0
            else:
                last_out = max(outs)
                shift_end_dt = datetime.combine(last_out.date(), end_t)
                if shift.get("is_night_shift") and last_out.time() < end_t:
                    # Last out is on the "morning after" — shift end is on
                    # the previous calendar day relative to last_out.
                    shift_end_dt = datetime.combine(last_out.date(), end_t)
                if last_out > shift_end_dt:
                    ot_hours = (last_out - shift_end_dt).total_seconds() / 3600
                else:
                    ot_hours = 0.0

    else:  # "After Standard Hours" (default)
        std_hours = flt(shift.get("standard_working_hours") or 8)
        if total_hours > std_hours:
            ot_hours = total_hours - std_hours

    # Apply threshold (minimum extra time before OT counts)
    if ot_hours <= threshold_hours:
        ot_hours = 0.0

    # Apply daily cap
    if max_ot and ot_hours > max_ot:
        ot_hours = max_ot

    return round(ot_hours, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Daily status classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_day(day_checkins, shift, doc_method, doc_missing_action):
    """
    Returns a dict with:
      status:        'Present' | 'Half Day' | 'Absent' | 'Invalid' | 'Manual Review'
      hours:         float working hours
      absent_hours:  float hours to count against employee
      overtime_hours: float overtime hours for the day
    """
    full_hours = flt(shift.get("full_day_hours") or 8)
    half_hours = flt(shift.get("half_day_hours") or 4)
    std_hours  = flt(shift.get("standard_working_hours") or 8)
    method     = doc_method or shift.get("working_hours_method") or "First IN - Last OUT"
    missing    = doc_missing_action or shift.get("missing_checkin_action") or "Mark as Invalid"

    # No checkins at all
    if not day_checkins:
        return {"status": "Absent", "hours": 0.0, "absent_hours": std_hours, "overtime_hours": 0.0}

    has_in  = any(c["log_type"] == "IN"  for c in day_checkins)
    has_out = any(c["log_type"] == "OUT" for c in day_checkins)

    # Handle missing IN or OUT
    if not (has_in and has_out):
        if missing == "Mark as Present":
            hours = calc_working_hours(day_checkins, method)
            ot = calc_overtime_hours(day_checkins, shift, hours)
            return {"status": "Present", "hours": hours, "absent_hours": 0.0, "overtime_hours": ot}
        elif missing == "Require Manual Review":
            return {"status": "Manual Review", "hours": 0.0, "absent_hours": 0.0, "overtime_hours": 0.0}
        else:  # Mark as Invalid
            return {"status": "Invalid", "hours": 0.0, "absent_hours": 0.0, "overtime_hours": 0.0}

    hours = calc_working_hours(day_checkins, method)
    ot = calc_overtime_hours(day_checkins, shift, hours)

    if hours >= full_hours:
        return {"status": "Present",  "hours": hours, "absent_hours": 0.0, "overtime_hours": ot}
    elif hours >= half_hours:
        return {"status": "Half Day", "hours": hours, "absent_hours": std_hours / 2, "overtime_hours": ot}
    else:
        return {"status": "Absent",   "hours": hours, "absent_hours": std_hours, "overtime_hours": ot}


# ─────────────────────────────────────────────────────────────────────────────
# Per-employee calculation
# ─────────────────────────────────────────────────────────────────────────────

def process_employee(employee, from_date, to_date,
                     checkin_list, default_shift_name,
                     doc_method, doc_missing_action):
    """
    Calculate attendance stats for one employee over the date range.
    Returns dict matching Attendance Summary Detail fields.
    """
    from_date = getdate(from_date)
    to_date   = getdate(to_date)
    working_days_list = get_working_days_in_range(from_date, to_date)

    # Use one representative shift for grouping (could be enhanced per-day)
    shift = get_shift_for_employee(employee, from_date, default_shift_name)

    daily_checkins = group_checkins_by_date(
        checkin_list, shift,
        default_method=doc_method,
        from_date=from_date, to_date=to_date
    )

    working_days      = 0.0
    absent_days       = 0.0
    half_days         = 0.0
    total_hours       = 0.0
    absent_hours      = 0.0
    overtime_hours    = 0.0
    overtime_days     = 0
    invalid_days      = 0
    manual_review_days = 0
    remarks_list      = []

    for work_date in working_days_list:
        day_shift    = get_shift_for_employee(employee, work_date, default_shift_name) or shift
        day_checkins = daily_checkins.get(work_date, [])

        result = classify_day(day_checkins, day_shift or {}, doc_method, doc_missing_action)

        total_hours    += result["hours"]
        absent_hours   += result["absent_hours"]
        overtime_hours += result.get("overtime_hours", 0.0)

        if result.get("overtime_hours", 0.0) > 0:
            overtime_days += 1

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

    return {
        "working_days":        round(working_days, 1),
        "absent_days":         round(absent_days, 1),
        "half_days":           half_days,
        "total_working_hours": round(total_hours, 2),
        "absent_hours":        round(absent_hours, 2),
        "overtime_hours":      round(overtime_hours, 2),
        "overtime_days":       overtime_days,
        "invalid_days":        invalid_days,
        "manual_review_days":  manual_review_days,
        "remarks":             ", ".join(remarks_list[:5]) if remarks_list else "",
    }
