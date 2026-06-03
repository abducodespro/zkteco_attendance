"""
Device Employee Mapping DocType controller.
Maps ZKTeco device user IDs to ERPNext Employee records.
"""
import frappe
from frappe import _
from frappe.model.document import Document


class DeviceEmployeeMapping(Document):
    """Controller for Device Employee Mapping DocType."""

    def validate(self):
        """Validate mapping uniqueness within a device."""
        self._check_duplicate_mapping()
        self._validate_employee_status()

    def _check_duplicate_mapping(self):
        """Ensure device_user_id is unique per device."""
        existing = frappe.db.get_value(
            "Device Employee Mapping",
            {
                "device": self.device,
                "device_user_id": self.device_user_id,
                "name": ["!=", self.name],
            },
            "name",
        )
        if existing:
            frappe.throw(
                _(
                    "Device User ID {0} is already mapped for device {1} in mapping {2}"
                ).format(self.device_user_id, self.device, existing)
            )

    def _validate_employee_status(self):
        """Warn if employee is not active."""
        status = frappe.db.get_value("Employee", self.employee, "status")
        if status and status != "Active":
            frappe.msgprint(
                _("Warning: Employee {0} has status '{1}'. Checkins will still be recorded.").format(
                    self.employee, status
                ),
                indicator="orange",
            )


def has_permission(doc, ptype, user):
    """Custom permission check."""
    if frappe.has_role("System Manager", user=user):
        return True
    if frappe.has_role("HR Manager", user=user):
        return True
    if frappe.has_role("Attendance Manager", user=user) and ptype in ("read", "write", "create"):
        return True
    return False


@frappe.whitelist()
def get_unmapped_device_users(device_name: str) -> list:
    """
    Return list of device users that don't have an employee mapping yet.
    Useful for the bulk-mapping UI.
    """
    from zkteco_attendance.zkteco_attendance.utils.zk_connector import ZKConnector

    device = frappe.get_doc("Biometric Device", device_name)
    connector = ZKConnector(device)

    try:
        zk_conn = connector.connect()
        users = zk_conn.get_users()
        connector.disconnect()
    except Exception as e:
        frappe.throw(_("Could not fetch users from device: {0}").format(str(e)))

    mapped_ids = frappe.get_all(
        "Device Employee Mapping",
        filters={"device": device_name, "active": 1},
        pluck="device_user_id",
    )

    unmapped = [
        {"user_id": str(u.user_id), "name": u.name, "privilege": u.privilege}
        for u in users
        if str(u.user_id) not in mapped_ids
    ]
    return unmapped


@frappe.whitelist()
def bulk_create_mappings(device_name: str, mappings: list) -> dict:
    """
    Bulk create Device Employee Mappings.

    Args:
        device_name: Biometric Device name
        mappings: List of {"device_user_id": str, "employee": str}
    """
    if isinstance(mappings, str):
        import json
        mappings = json.loads(mappings)

    created = 0
    errors = []

    for m in mappings:
        try:
            doc = frappe.new_doc("Device Employee Mapping")
            doc.device = device_name
            doc.device_user_id = str(m["device_user_id"])
            doc.employee = m["employee"]
            doc.active = 1
            doc.insert(ignore_permissions=True)
            created += 1
        except Exception as e:
            errors.append(f"User ID {m.get('device_user_id')}: {str(e)}")

    frappe.db.commit()
    return {
        "created": created,
        "errors": errors,
        "message": _("{0} mappings created, {1} errors").format(created, len(errors)),
    }
