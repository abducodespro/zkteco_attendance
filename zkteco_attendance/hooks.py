app_name = "zkteco_attendance"
app_title = "ZKTeco Attendance"
app_publisher = "Your Organization"
app_description = "ZKTeco Biometric Attendance Integration for ERPNext/Frappe v14"
app_email = "admin@example.com"
app_license = "MIT"
app_version = "1.0.0"

# DocType JS — loaded when the DocType form is opened
doctype_js = {
    "Biometric Device": "public/js/biometric_device.bundle.js",
}

# Installation
# ------------
after_install = "zkteco_attendance.install.after_install"
after_migrate = "zkteco_attendance.install.after_migrate"

# Scheduler Events
# ----------------
scheduler_events = {
    "cron": {
        "*/5 * * * *": [
            "zkteco_attendance.scheduler.jobs.sync_5min_devices"
        ],
        "*/15 * * * *": [
            "zkteco_attendance.scheduler.jobs.sync_15min_devices"
        ],
        "*/30 * * * *": [
            "zkteco_attendance.scheduler.jobs.sync_30min_devices"
        ],
    },
    "hourly": [
        "zkteco_attendance.scheduler.jobs.sync_hourly_devices"
    ],
    "daily": [
        "zkteco_attendance.scheduler.jobs.sync_daily_devices",
        "zkteco_attendance.scheduler.jobs.cleanup_old_logs",
    ],
}

# Permissions
# -----------
has_permission = {
    "Biometric Device": "zkteco_attendance.doctype.biometric_device.biometric_device.has_permission",
    "Attendance Sync Log": "zkteco_attendance.doctype.attendance_sync_log.attendance_sync_log.has_permission",
    "Device Employee Mapping": "zkteco_attendance.doctype.device_employee_mapping.device_employee_mapping.has_permission",
}

# Document Events
# ---------------
doc_events = {
    "Biometric Device": {
        "before_save": "zkteco_attendance.doctype.biometric_device.biometric_device.before_save",
        "on_trash": "zkteco_attendance.doctype.biometric_device.biometric_device.on_trash",
    }
}
