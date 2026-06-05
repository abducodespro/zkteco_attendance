# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document


class DeviceEmployeeMapping(Document):

    def validate(self):
        existing = frappe.db.get_value(
            "Device Employee Mapping",
            {"device": self.device, "device_user_id": self.device_user_id, "name": ["!=", self.name]},
            "name",
        )
        if existing:
            frappe.throw(_("Device User ID {0} is already mapped for device {1}").format(
                self.device_user_id, self.device
            ))


def has_permission(doc, ptype, user):
    if frappe.has_role("System Manager", user=user):
        return True
    if frappe.has_role("HR Manager", user=user):
        return True
    if frappe.has_role("Attendance Manager", user=user) and ptype in ("read", "write", "create"):
        return True
    return False
