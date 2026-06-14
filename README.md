# ZKTeco Attendance for ERPNext / Frappe

Connects ZKTeco biometric devices to ERPNext: pulls attendance punches,
creates **Employee Checkin** records, and processes them into attendance
summaries with overtime support. Compatible with Frappe/ERPNext v14, v15,
and v16.

---

## 1. Installation

```bash
bench get-app zkteco_attendance <repo-url-or-path>
bench --site yoursite.local install-app zkteco_attendance
bench --site yoursite.local migrate
bench build --app zkteco_attendance
bench restart
```

Make sure the `pyzk` Python library is available (used to talk to the
device over the network):

```bash
pip install pyzk --break-system-packages
```

Installation automatically:
- Creates a **Biometric Device Manager** role
- Adds a **Biometric Attendance ID** field to Employee
- Adds **Biometric Device**, **ZK Device Record ID**, and **Overtime
  Punch** fields to Employee Checkin

---

## 2. Initial Setup

### 2.1 Map employees to the device
On each **Employee** record, fill in **Biometric Attendance ID** — this
must match the User ID/Badge Number enrolled on the ZKTeco device for that
person.

### 2.2 Add a Biometric Device
Go to **Biometric Device** (new) and fill in:

| Field | Notes |
|---|---|
| Device Name | Any label, must be unique |
| Device IP / Port | Device's network address (default port 4370) |
| Company | Company this device belongs to |
| Connection Password | Only if the device has a comm key/password set |
| Status | Set to **Active** once configured |
| Auto Sync Enabled / Sync Frequency | 5 Min / 15 Min / 30 Min / Hourly / Daily — for the background scheduler |
| Fetch Mode | **New Records Only** (recommended) or **All Records** |
| Clear Device Logs After Sync | Frees device memory after each pull — use with care |
| Device Clock Offset (minutes) | Leave at **0** unless this specific device's clock is known to be wrong. Device timestamps are taken as-is (assumed to already be correct local time) |
| Treat OT Punch Codes (4/5) as Overtime | If enabled, device punch codes 4 (OT In) / 5 (OT Out) are recorded as overtime punches |

Click **Test Connection** to verify the device responds and to see its
serial number, firmware, enrolled users, and stored log count.

### 2.3 Set up Shift Types
Create one or more **ZK Shift Type** records:

- **Timing**: Start Time, End Time, Is Night Shift (for shifts crossing
  midnight)
- **Hours**: Full Day Hours, Half Day Hours, Standard Working Hours
- **Calculation**: Working Hours Method (First IN–Last OUT or Actual Pairs),
  Missing Check-In/Out Action (Mark Invalid / Present / Manual Review)
- **Grace Periods**: Late Entry / Early Exit grace in minutes
- **Overtime Management** (optional, see section 5)

### 2.4 Assign shifts
Use **ZK Shift Assignment** to assign a Shift Type to a group of employees
for a date range (From Date / To Date, Status = Active).

---

## 3. Pulling Attendance (Pull Checkins)

Open a **Biometric Device** record and click **Pull Checkins** (under
*Actions*):

1. Confirm the dialog — this connects to the device right away.
2. A progress dialog shows live stages: connecting → fetching records →
   processing → creating Employee Checkins → done.
3. When finished, you'll see a summary: **Total Pulled**, **New**,
   **Duplicates**, **Failed**, **Overtime Punches**, and overall **Status**
   (Success / Partial / Failed).

Each pull creates **Employee Checkin** records with `log_type` of `IN` or
`OUT`. Devices that send the same punch code for every tap are handled
automatically — punches for each employee/day are alternated IN, OUT, IN,
OUT in chronological order. Explicit overtime punches (codes 4/5, if
enabled) are flagged with the **Overtime Punch** checkbox instead.

**Test Connection** can be run at any time to re-check connectivity without
pulling data.

**View Sync Logs** opens the **Attendance Sync Log** list filtered to that
device — useful history of every pull (manual or scheduled), including
counts and any errors.

### Automatic syncing
If **Auto Sync Enabled** is checked, the background scheduler pulls
checkins automatically at the configured **Sync Frequency**, independent of
the manual button above. Logs from scheduled pulls also appear in
**Attendance Sync Log** (Triggered By = Scheduler).

---

## 4. Processing Attendance (Attendance Summary)

Use **Attendance Summary** to turn raw checkins into a per-employee
attendance report for a date range:

1. Create a new **Attendance Summary**, set **Company**, **From Date**,
   **To Date**, and optionally a default **Shift Type** (used as a fallback
   if an employee has no Shift Assignment).
2. Click **Fetch Employees** — choose to fetch all active employees, or
   filter by Department / Designation / Project.
3. Click **Process Attendance**. This runs in the background; the form
   polls automatically and reloads when done.
4. Each row in **Details** shows: Working Days, Absent Days, Half Days,
   Total Hours, Absent Hours, **Overtime Hours**, OT Days, Invalid Days, and
   Manual Review flags.
5. The summary totals show **Total Employees**, **Working Days in Period**,
   and **Total Overtime Hours**.

**Working Hours Method**:
- *First IN – Last OUT*: total span between the first and last punch of the
  day.
- *Actual Pairs (IN-OUT)*: sums each matched IN→OUT pair (more accurate if
  employees punch for breaks too).

**Missing Check-In/Out Action** controls what happens on days with only one
punch:
- *Mark as Invalid* — excluded from hours, flagged for review.
- *Mark as Present* — counted using available punches.
- *Require Manual Review* — flagged, no hours counted.

---

## 5. Overtime Management

Enable overtime per shift on **ZK Shift Type** → **Overtime Management**
section:

- **Enable Overtime Calculation** — turns OT on for this shift.
- **Overtime Calculation Method**:
  - *After Standard Hours* — any hours worked beyond **Standard Working
    Hours** count as OT.
  - *After Shift End Time* — time worked past the shift's **End Time**
    counts as OT.
  - *OT Punches Only* — only explicit device OT In/Out punches (codes 4/5)
    count as OT.
- **OT Threshold (minutes)** — minimum extra time before OT is counted
  (avoids paying OT for a few minutes of rounding).
- **Overtime Rate Multiplier** — reference value only; actual pay rules
  belong in Payroll.
- **Max OT Hours per Day** — optional daily cap (0 = no cap).

Resulting overtime hours/days appear automatically in **Attendance Summary
Detail** and **Attendance Summary** after processing.

---

## 6. Dashboard & Workspace Chart

The **Biometric Attendance** workspace includes a built-in **Check-ins
(Last 7 Days)** bar chart at the top, showing daily Employee Checkin counts
for the past week — refreshable from the chart's own menu like any other
workspace chart.

The **ZKTeco Dashboard** page (search for it in the awesome bar) shows:

- Total / Online / Offline device counts
- Today's check-in count and failed syncs today
- Last sync time
- Charts: check-ins (last 7 days), sync results (last 7 days), device
  status, and today's IN/OUT/Overtime breakdown

Use the menu's **Sync All Devices** to queue a background sync for every
active device, or **Refresh** to reload the data. The page auto-refreshes
every 60 seconds.

---

## 7. Permissions

Three roles can access this app's doctypes: **System Manager**, **HR
Manager**, and **Biometric Device Manager** (created automatically on
install — assign it to users who should manage devices/syncs without full
HR or System Manager access).

---

## 8. Troubleshooting

- **Connection failed** — check Device IP/Port, that the device is on the
  same network/VPN as the ERPNext server, and that no firewall blocks the
  port (default 4370).
- **No employee found for biometric ID** — make sure the **Biometric
  Attendance ID** on the Employee exactly matches the device's enrolled
  User ID, and that the employee's **Status** is Active.
- **Check-in times look wrong** — leave **Device Clock Offset (minutes)** at
  0 first; device timestamps are stored as-is. Only set an offset if you've
  confirmed the device's own clock is incorrect.
- **Pull takes a long time / times out** — for devices with thousands of
  stored logs, ensure your web server/reverse proxy timeout is generous
  (5–10 minutes), or use **Clear Device Logs After Sync** to keep device
  storage small.
- Check **Attendance Sync Log** for a history of every sync attempt and any
  error details.

---

#### License

MIT
