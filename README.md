# ZKTeco Attendance — ERPNext/Frappe Custom App

A production-ready integration between **ZKTeco biometric attendance devices** and **ERPNext v15/v16** over your local network.

---

## Features

| Feature | Details |
|---|---|
| **Device Support** | K40, MB20, UFace, iFace, F18, SpeedFace, and all ZKTeco models using the ZK protocol |
| **Auto Sync** | Scheduler-based sync at 5 min / 15 min / 30 min / Hourly / Daily intervals |
| **Manual Sync** | One-click "Sync Now" from the device form or dashboard |
| **Timezone Handling** | Per-device timezone config with automatic UTC conversion |
| **Duplicate Detection** | Cached duplicate check — no double-posting of Employee Checkins |
| **Audit Trail** | Full Attendance Sync Log with per-sync record counts and error details |
| **Employee Mapping** | Map device User IDs → ERPNext Employees via Device Employee Mapping |
| **Dashboard** | Real-time dashboard showing device status, today's checkins, and recent sync logs |
| **Background Jobs** | All sync operations run in Frappe's background job queue (no UI blocking) |
| **Security** | Encrypted password storage, role-based permissions (HR Manager / Attendance Manager) |

---

## Requirements

- ERPNext / Frappe **v15 or v16**
- Python **3.11+**
- MariaDB
- `pyzk` library (installed automatically)
- Network access from the Frappe server to the ZKTeco devices (TCP port 4370 by default)

---

## Installation

```bash
# 1. Get the app into your bench
cd /home/frappe/frappe-bench
bench get-app zkteco_attendance /path/to/zkteco_attendance
# OR from git:
# bench get-app https://github.com/your-org/zkteco_attendance

# 2. Install on your site
bench --site your-site.local install-app zkteco_attendance

# 3. Run migration
bench --site your-site.local migrate

# 4. Restart all services
bench restart
```

> **pyzk** is listed in `requirements.txt` and will be installed automatically by `bench install-app`.
> If you need to install manually: `./env/bin/pip install pyzk`

---

## Quick Start

### 1. Add a Device

Go to **ZKTeco Attendance → Biometric Device → New**

| Field | Example |
|---|---|
| Device Name | `Main Entrance` |
| Device IP | `192.168.1.201` |
| Port | `4370` |
| Company | `Acme Corp` |
| Time Zone | `Africa/Addis_Ababa` |
| Status | `Active` |
| Auto Sync Enabled | ✅ |
| Sync Frequency | `15 Min` |
| Fetch Mode | `New Records Only` |

Click **Actions → Test Connection** to verify connectivity.

### 2. Map Employees

Go to **ZKTeco Attendance → Device Employee Mapping → New**

| Field | Value |
|---|---|
| Device | `Main Entrance` |
| Device User ID | `1` (the ID stored on the device) |
| Employee | `EMP-0001` |

Repeat for each enrolled user.

### 3. Sync

- **Manual**: Open the device form → **Actions → Sync Now**
- **Dashboard**: **ZKTeco Attendance → ZKTeco Dashboard → Sync All Devices**
- **Automatic**: Enabled automatically if *Auto Sync Enabled* is checked and the scheduler is running

### 4. View Results

- **Employee Checkin**: Standard ERPNext list — all checkins appear here
- **Attendance Sync Log**: Full per-sync audit trail
- **ZKTeco Dashboard**: Live overview of all devices and recent syncs

---

## Architecture

```
zkteco_attendance/
├── setup.py
├── requirements.txt
├── MANIFEST.in
├── zkteco_attendance/
│   ├── hooks.py                        # App hooks, scheduler events
│   ├── install.py                      # Post-install setup
│   ├── doctype/
│   │   ├── biometric_device/
│   │   │   ├── biometric_device.json   # DocType schema
│   │   │   └── biometric_device.py    # Controller + whitelisted API
│   │   ├── attendance_sync_log/
│   │   │   ├── attendance_sync_log.json
│   │   │   └── attendance_sync_log.py
│   │   └── device_employee_mapping/
│   │       ├── device_employee_mapping.json
│   │       └── device_employee_mapping.py
│   ├── page/
│   │   └── zkteco_dashboard/
│   │       ├── zkteco_dashboard.json   # Page registration
│   │       ├── zkteco_dashboard.py
│   │       └── zkteco_dashboard.js    # Dashboard UI
│   ├── scheduler/
│   │   └── jobs.py                     # Scheduler entry points
│   ├── utils/
│   │   ├── zk_connector.py            # ZKTeco device communication (pyzk)
│   │   └── sync_engine.py             # Core sync orchestration
│   └── workspace/
│       └── zkteco_attendance.json     # Frappe desk workspace
└── public/
    ├── js/
    │   ├── biometric_device.js         # Form-level JS (Test/Sync buttons)
    │   └── zkteco_attendance.js        # Global app JS
    └── css/
        └── zkteco_attendance.css       # Global styles
```

---

## API Reference

All methods are whitelisted for use from the Frappe client or REST API.

### `test_connection(device_name)`
Returns device serial, firmware version, time, user count, and attendance record count.

### `sync_device(device_name, triggered_by="Manual")`
Enqueues a background sync job for the specified device.

### `sync_all_devices()`
Enqueues sync jobs for all active devices.

### `get_device_status(device_name)`
Returns current status and last sync log summary.

### `get_sync_logs(device_name=None, limit=20)`
Returns recent sync log entries, optionally filtered by device.

### `get_dashboard_stats()`
Returns aggregated stats for the dashboard.

---

## Timezone Handling

- Each Biometric Device has a **Time Zone** field.
- ZKTeco devices store timestamps as naive datetimes in the device's local clock.
- The sync engine **localizes** those timestamps to the configured timezone, then **converts to UTC** before storing in ERPNext.
- This correctly handles: DST transitions, devices in different timezones, night shifts crossing midnight.

---

## Duplicate Prevention

The sync engine uses a two-layer deduplication strategy:

1. **Pre-load cache**: At the start of each sync, all existing `Employee Checkin` records for the device in the past 30 days are loaded into an in-memory set.
2. **Per-record check**: Each incoming record is checked against the cache before inserting.

This avoids costly per-record DB queries and handles re-syncing of already-processed records gracefully.

---

## Permissions

| Role | Biometric Device | Sync Log | Employee Mapping |
|---|---|---|---|
| System Manager | Full | Full | Full |
| HR Manager | Full | Read | Full |
| Attendance Manager | Read/Write | Read | Read/Write |

---

## Troubleshooting

### "pyzk library not installed"
```bash
cd /home/frappe/frappe-bench
./env/bin/pip install pyzk
bench restart
```

### "Connection timed out"
- Check that the device IP is reachable from the Frappe server: `ping 192.168.1.201`
- Ensure port 4370 is open: `nc -zv 192.168.1.201 4370`
- Check firewall rules on both the server and network switches.

### "Connection refused"
- The device may be busy processing a card swipe. Try again in a moment.
- Verify the correct port (most ZKTeco devices use 4370).

### "Authentication failed"
- Set the correct **Connection Password** in the device form.
- Many devices ship with no password (leave the field blank).

### Scheduler not running
```bash
bench --site your-site.local doctor
bench start  # in development
# or check systemd / supervisor in production
```

---

## Compatibility

Tested with: **K40, MB20, UFace 800, iFace 800, F18, SpeedFace V5L, ZK9500, MA300**

Any device supporting the ZKTeco binary protocol over TCP (port 4370) should work.

---

## License

MIT License — see LICENSE file for details.
