from frappe import _

def get_data():
    return [
        {
            "module_name": "Zkteco Attendance",
            "color": "#2490ef",
            "icon": "octicon octicon-device-mobile",
            "type": "module",
            "label": _("ZKTeco Attendance"),
            "items": [
                {
                    "type": "page",
                    "name": "zkteco-dashboard",
                    "label": _("Dashboard"),
                },
                {
                    "type": "doctype",
                    "name": "Biometric Device",
                    "label": _("Biometric Devices"),
                },
                {
                    "type": "doctype",
                    "name": "Attendance Sync Log",
                    "label": _("Sync Logs"),
                },
            ],
        }
    ]
