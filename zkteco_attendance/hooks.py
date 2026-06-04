app_name = "zkteco_attendance"
app_title = "ZKTeco Attendance"
app_publisher = "Your Organization"
app_description = "ZKTeco Biometric Attendance Integration for ERPNext/Frappe v15/v16"
app_email = "admin@example.com"
app_license = "MIT"
app_version = "1.0.0"

# Required Apps
required_apps = ["erpnext"]

# -----------------------------------------------------------------
# Asset Includes
# app_include_css / app_include_js require a proper esbuild bundle
# entry-point declared in package.json. We skip the global JS
# include entirely — the dashboard page JS is loaded by the Page
# framework automatically, and doctype_js handles form JS.
# -----------------------------------------------------------------

# DocType JS — loaded only when that DocType form is opened.
# Frappe serves these files directly from the app's public/ folder;
# they do NOT go through esbuild, so no package.json entry needed.
doctype_js = {
    "Biometric Device": "public/js/biometric_device.js",
}

# Fixtures
fixtures = [
    {"dt": "Role", "filters": [["name", "in", ["HR Manager", "Attendance Manager"]]]},
    {"dt": "Workspace", "filters": [["module", "=", "ZKTeco Attendance"]]},
]

# Installation
# ------------
after_install = "zkteco_attendance.install.after_install"
after_migrate = "zkteco_attendance.install.after_migrate"

# Scheduler Events
# ----------------
scheduler_events = {
    "cron": {
        # Every 5 minutes
        "*/5 * * * *": [
            "zkteco_attendance.zkteco_attendance.scheduler.jobs.sync_5min_devices"
        ],
        # Every 15 minutes
        "*/15 * * * *": [
            "zkteco_attendance.zkteco_attendance.scheduler.jobs.sync_15min_devices"
        ],
        # Every 30 minutes
        "*/30 * * * *": [
            "zkteco_attendance.zkteco_attendance.scheduler.jobs.sync_30min_devices"
        ],
    },
    "hourly": [
        "zkteco_attendance.zkteco_attendance.scheduler.jobs.sync_hourly_devices"
    ],
    "daily": [
        "zkteco_attendance.zkteco_attendance.scheduler.jobs.sync_daily_devices",
        "zkteco_attendance.zkteco_attendance.scheduler.jobs.cleanup_old_logs",
    ],
}

# Permissions
# -----------
has_permission = {
    "Biometric Device": "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.has_permission",
    "Attendance Sync Log": "zkteco_attendance.zkteco_attendance.doctype.attendance_sync_log.attendance_sync_log.has_permission",
    "Device Employee Mapping": "zkteco_attendance.zkteco_attendance.doctype.device_employee_mapping.device_employee_mapping.has_permission",
}

# Document Events
# ---------------
doc_events = {
    "Biometric Device": {
        "before_save": "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.before_save",
        "on_trash": "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.on_trash",
    }
}
