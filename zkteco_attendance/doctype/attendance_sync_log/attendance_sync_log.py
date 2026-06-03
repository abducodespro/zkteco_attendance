"""
Attendance Sync Log DocType controller.
Provides an audit trail for every sync operation.
"""
import frappe
from frappe.model.document import Document


class AttendanceSyncLog(Document):
    """Controller for Attendance Sync Log DocType."""

    def before_insert(self):
        """Set default start time on creation."""
        if not self.start_time:
            self.start_time = frappe.utils.now_datetime()

    def mark_complete(self, total, created, duplicates, failed, errors=None):
        """Mark this log as successfully completed."""
        self.end_time = frappe.utils.now_datetime()
        self.total_records_pulled = total
        self.new_records_created = created
        self.duplicate_records = duplicates
        self.failed_records = failed

        if failed > 0 and created > 0:
            self.sync_status = "Partial"
        elif failed > 0 and created == 0:
            self.sync_status = "Failed"
        else:
            self.sync_status = "Success"

        if errors:
            self.error_details = "\n".join(str(e) for e in errors)

        self.save(ignore_permissions=True)
        frappe.db.commit()

    def mark_failed(self, error_message: str):
        """Mark this log as failed with an error message."""
        self.end_time = frappe.utils.now_datetime()
        self.sync_status = "Failed"
        self.error_details = str(error_message)
        self.save(ignore_permissions=True)
        frappe.db.commit()


def has_permission(doc, ptype, user):
    """Custom permission check."""
    if frappe.has_role("System Manager", user=user):
        return True
    if frappe.has_role("HR Manager", user=user) and ptype == "read":
        return True
    if frappe.has_role("Attendance Manager", user=user) and ptype == "read":
        return True
    return False
