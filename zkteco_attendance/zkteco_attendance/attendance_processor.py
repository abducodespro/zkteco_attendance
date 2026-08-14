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
    "overtime_threshold_minutes", "overtime_rate_multiplier",
    "max_overtime_hours_per_day",
    "day_overtime_rate", "night_overtime_rate",
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
    Returns dict: { employee -> [ {time, log_type, is_overtime, manually_edited, edited_by, edited_at}, ... ] }
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
        SELECT employee, time, log_type{extra}
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

def calc_overtime_hours(day_checkins, shift, total_hours):
    """
    Calculate overtime hours for one day.
    Returns a dict:
      {
        ot_hours:        total overtime hours,
        day_ot_hours:    hours at day OT rate (e.g. 1.5x),
        night_ot_hours:  hours at night OT rate (e.g. 1.75x),
      }
    Returns zeros dict if overtime is not enabled on the shift.

    Guard shift examples handled:
    ─ Night guard: clock in 17:00, clock out 06:00.
        Standard 8 hrs → 17:00–01:00. Night OT window 01:00–06:00 = 5 hrs (1.75×).
        Set: night_ot_start_time=01:00, night_ot_end_time=06:00, night_overtime_rate=1.75
    ─ Day guard: clock in 06:00, clock out 17:00.
        Day OT window before standard start: 06:00–08:00 = 2 hrs (1.5×).
        Set: standard_start_time=08:00, day_overtime_rate=1.5
    """
    zero = {"ot_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0}
    if not shift or not shift.get("enable_overtime"):
        return zero

    method = shift.get("overtime_calculation_method") or "After Standard Hours"
    threshold_minutes = flt(shift.get("overtime_threshold_minutes") or 0)
    threshold_hours   = threshold_minutes / 60.0
    max_ot            = flt(shift.get("max_overtime_hours_per_day") or 0)

    total_ot   = 0.0
    day_ot     = 0.0
    night_ot   = 0.0

    if method == "OT Punches Only":
        ot_checkins = [c for c in day_checkins if c.get("is_overtime")]
        total_ot = calc_hours_actual_pairs(ot_checkins)

    elif method == "After Shift End Time":
        end_str = shift.get("end_time")
        if end_str and day_checkins:
            end_t = _coerce_time(end_str)
            outs  = [c["time"] for c in day_checkins if c["log_type"] == "OUT"]
            if outs:
                last_out      = max(outs)
                shift_end_dt  = datetime.combine(last_out.date(), end_t)
                if last_out > shift_end_dt:
                    total_ot = (last_out - shift_end_dt).total_seconds() / 3600

    else:  # "After Standard Hours" (default) + guard window logic
        std_hours = flt(shift.get("standard_working_hours") or 8)

        # ── Guard Night OT window ─────────────────────────────────────────
        night_ot_start_str = shift.get("night_ot_start_time")
        night_ot_end_str   = shift.get("night_ot_end_time")
        if night_ot_start_str and night_ot_end_str and day_checkins:
            not_start = _coerce_time(night_ot_start_str)
            not_end   = _coerce_time(night_ot_end_str)

            # Last OUT of the day (or night)
            outs = sorted([c["time"] for c in day_checkins if c["log_type"] == "OUT"])
            ins  = sorted([c["time"] for c in day_checkins if c["log_type"] == "IN"])

            if outs and ins:
                first_in = ins[0]
                last_out = outs[-1]

                # Build night OT boundary datetimes relative to checkout date
                # Night OT start is on the same date as last_out (early morning)
                not_start_dt = datetime.combine(last_out.date(), not_end)   # e.g. 06:00 same day
                not_begin_dt = datetime.combine(last_out.date(), not_start) # e.g. 01:00 same day

                # If not_begin (01:00) is before last_out and not_start (06:00) is >= last_out
                # i.e. employee was present through the night OT window
                if last_out > not_begin_dt:
                    clipped_end = min(last_out, not_start_dt)
                    overlap = (clipped_end - not_begin_dt).total_seconds() / 3600
                    night_ot = max(0.0, overlap)

        # ── Guard Day OT window (pre-standard start) ──────────────────────
        std_start_str = shift.get("standard_start_time")
        if std_start_str and day_checkins:
            std_start_t = _coerce_time(std_start_str)
            ins = sorted([c["time"] for c in day_checkins if c["log_type"] == "IN"])
            if ins:
                first_in = ins[0]
                std_start_dt = datetime.combine(first_in.date(), std_start_t)
                if first_in < std_start_dt:
                    day_ot = (std_start_dt - first_in).total_seconds() / 3600

        # If no time-window OT was configured, fall back to After Standard Hours
        if night_ot == 0.0 and day_ot == 0.0 and total_hours > std_hours:
            total_ot = total_hours - std_hours

    # Combine windowed OT
    if night_ot > 0.0 or day_ot > 0.0:
        total_ot = night_ot + day_ot

    # Apply threshold
    if total_ot <= threshold_hours:
        total_ot = 0.0
        day_ot   = 0.0
        night_ot = 0.0

    # Apply daily cap
    if max_ot and total_ot > max_ot:
        # Cap proportionally
        scale = max_ot / total_ot
        day_ot   = round(day_ot   * scale, 2)
        night_ot = round(night_ot * scale, 2)
        total_ot = max_ot

    return {
        "ot_hours":       round(total_ot, 2),
        "day_ot_hours":   round(day_ot,   2),
        "night_ot_hours": round(night_ot, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Daily status classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_day(day_checkins, shift, doc_method, doc_missing_action, is_saturday=False):
    """
    Returns a dict with attendance status, hours, and overtime breakdown.
    When is_saturday=True, applies Saturday-specific hour thresholds.
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

    empty_ot = {"ot_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0}

    # No checkins at all
    if not day_checkins:
        return {"status": "Absent", "hours": 0.0, "absent_hours": std_hours,
                "overtime_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0}

    has_in  = any(c["log_type"] == "IN"  for c in day_checkins)
    has_out = any(c["log_type"] == "OUT" for c in day_checkins)

    if not (has_in and has_out):
        if missing == "Mark as Present":
            hours = calc_working_hours(day_checkins, method)
            ot = calc_overtime_hours(day_checkins, shift, hours)
            return {"status": "Present", "hours": hours, "absent_hours": 0.0,
                    "overtime_hours": ot["ot_hours"], "day_ot_hours": ot["day_ot_hours"],
                    "night_ot_hours": ot["night_ot_hours"]}
        elif missing == "Require Manual Review":
            return {"status": "Manual Review", "hours": 0.0, "absent_hours": 0.0,
                    "overtime_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0}
        else:
            return {"status": "Invalid", "hours": 0.0, "absent_hours": 0.0,
                    "overtime_hours": 0.0, "day_ot_hours": 0.0, "night_ot_hours": 0.0}

    hours = calc_working_hours(day_checkins, method)
    ot    = calc_overtime_hours(day_checkins, shift, hours)

    if is_saturday and saturday_mode == "Half Day":
        # Saturday with any attendance → half day, no absent hours
        return {"status": "Half Day", "hours": hours, "absent_hours": 0.0,
                "overtime_hours": ot["ot_hours"], "day_ot_hours": ot["day_ot_hours"],
                "night_ot_hours": ot["night_ot_hours"]}

    if hours >= full_hours:
        return {"status": "Present", "hours": hours, "absent_hours": 0.0,
                "overtime_hours": ot["ot_hours"], "day_ot_hours": ot["day_ot_hours"],
                "night_ot_hours": ot["night_ot_hours"]}
    elif hours >= half_hours:
        return {"status": "Half Day", "hours": hours, "absent_hours": std_hours / 2,
                "overtime_hours": ot["ot_hours"], "day_ot_hours": ot["day_ot_hours"],
                "night_ot_hours": ot["night_ot_hours"]}
    else:
        return {"status": "Absent", "hours": hours, "absent_hours": std_hours,
                "overtime_hours": ot["ot_hours"], "day_ot_hours": ot["day_ot_hours"],
                "night_ot_hours": ot["night_ot_hours"]}


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
    working_days_list = get_working_days_in_range(from_date, to_date, saturday_mode)

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
    overtime_days      = 0
    invalid_days       = 0
    manual_review_days = 0
    remarks_list       = []

    for work_date in working_days_list:
        day_shift    = get_shift_for_employee(employee, work_date, default_shift_name) or shift
        day_checkins = daily_checkins.get(work_date, [])
        is_saturday  = (work_date.weekday() == 5)

        result = classify_day(day_checkins, day_shift or {}, doc_method, doc_missing_action,
                               is_saturday=is_saturday)

        total_hours    += result["hours"]
        absent_hours   += result["absent_hours"]
        overtime_hours += result.get("overtime_hours", 0.0)
        day_ot_hours   += result.get("day_ot_hours", 0.0)
        night_ot_hours += result.get("night_ot_hours", 0.0)

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
        "day_ot_hours":        round(day_ot_hours, 2),
        "night_ot_hours":      round(night_ot_hours, 2),
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
    working_days_list = get_working_days_in_range(from_date, to_date, saturday_mode)

    daily_checkins = group_checkins_by_date(
        checkin_list, shift,
        default_method=doc_method,
        from_date=from_date, to_date=to_date
    )

    breakdown = []
    for work_date in working_days_list:
        day_shift    = get_shift_for_employee(employee, work_date, default_shift_name) or shift or {}
        day_checkins = sorted(daily_checkins.get(work_date, []), key=lambda c: c["time"])
        is_saturday  = (work_date.weekday() == 5)

        result = classify_day(day_checkins, day_shift, doc_method, doc_missing_action,
                               is_saturday=is_saturday)

        breakdown.append({
            "date":           str(work_date),
            "weekday":        work_date.strftime("%A"),
            "is_saturday":    is_saturday,
            "status":         result["status"],
            "hours":          result["hours"],
            "overtime_hours": result.get("overtime_hours", 0.0),
            "day_ot_hours":   result.get("day_ot_hours", 0.0),
            "night_ot_hours": result.get("night_ot_hours", 0.0),
            "checkins": [
                {
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
