import frappe
from frappe import _
from frappe.model.document import Document


class ZKShiftAssignment(Document):

    def validate(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            frappe.throw(_("From Date cannot be after To Date."))
        self._check_duplicate_assignments()

    def _check_duplicate_assignments(self):
        """Warn if any employee already has an active assignment overlapping this period."""
        for row in self.employees:
            if not row.employee:
                continue
            conflict = frappe.db.sql("""
                SELECT sa.name, sa.shift_type, sa.from_date, sa.to_date
                FROM `tabZK Shift Assignment` sa
                JOIN `tabZK Shift Assignment Employee` sae ON sae.parent = sa.name
                WHERE sae.employee = %s
                  AND sa.name != %s
                  AND sa.status = 'Active'
                  AND sa.from_date <= %s
                  AND sa.to_date   >= %s
            """, (row.employee, self.name or "NEW", self.to_date, self.from_date), as_dict=True)

            if conflict:
                frappe.msgprint(
                    _("Employee {0} already has an active shift assignment ({1}) overlapping this period.").format(
                        row.employee, conflict[0].name
                    ),
                    alert=True, indicator="orange"
                )


@frappe.whitelist()
def get_employees_for_assignment(department=None, project=None, job_title=None, company=None):
    """Fetch active employees matching optional filters for bulk-add to shift assignment."""
    filters = {"status": "Active"}
    if company:        filters["company"]         = company
    if department:     filters["department"]      = department
    if project:         filters["project"]          = project
    if job_title:      filters["job_title"]       = job_title

    return frappe.get_all(
        "Employee",
        filters=filters,
        fields=["name as employee", "employee_name", "department", "designation"],
        order_by="employee_name asc"
    )
