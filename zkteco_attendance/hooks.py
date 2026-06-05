# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "zkteco_attendance"
app_title = "ZKTeco Attendance"
app_publisher = "Your Organization"
app_description = "ZKTeco Biometric Attendance Integration for ERPNext/Frappe"
app_icon = "octicon octicon-device-mobile"
app_color = "blue"
app_email = "admin@example.com"
app_license = "MIT"

# Includes in <head>
# app_include_css = "/assets/zkteco_attendance/css/zkteco_attendance.css"
app_include_js = ["zkteco_attendance.bundle.js"]

# DocType JS
doctype_js = {
    "Biometric Device": "public/js/biometric_device.bundle.js",
}

# Installation
after_install = "zkteco_attendance.install.after_install"
after_migrate = "zkteco_attendance.install.after_migrate"

# Scheduler Events
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
has_permission = {
    "Biometric Device": "zkteco_attendance.doctype.biometric_device.biometric_device.has_permission",
    "Attendance Sync Log": "zkteco_attendance.doctype.attendance_sync_log.attendance_sync_log.has_permission",
    "Device Employee Mapping": "zkteco_attendance.doctype.device_employee_mapping.device_employee_mapping.has_permission",
}

# Document Events
doc_events = {
    "Biometric Device": {
        "before_save": "zkteco_attendance.doctype.biometric_device.biometric_device.before_save",
        "on_trash": "zkteco_attendance.doctype.biometric_device.biometric_device.on_trash",
    }
}
