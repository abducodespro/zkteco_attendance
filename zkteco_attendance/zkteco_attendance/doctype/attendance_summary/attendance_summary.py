"""
Attendance Summary DocType Controller
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, flt

from zkteco_attendance.zkteco_attendance.attendance_processor import (
    count_working_days,
    fetch_checkins,
    process_employee,
)


class AttendanceSummary(Document):

    def validate(self):
        if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))

    # ── called by JS "Fetch Employees" after filter dialog ───────────────────
    # @frappe.whitelist()
    # def fetch_employees(self, department=None, designation=None, project=None,
    #                     branch=None, employment_type=None):
    #     """
    #     Fetch active employees matching filters and populate the details child table.
    #     Preserves existing rows that match; appends new ones.
    #     """
    #     filters = {"status": "Active"}
    #     if self.company:         filters["company"]         = self.company
    #     if department:           filters["department"]      = department
    #     if designation:          filters["designation"]     = designation
    #     if branch:               filters["branch"]          = branch
    #     if employment_type:      filters["employment_type"] = employment_type

    #     employees = frappe.get_all(
    #         "Employee", filters=filters,
    #         fields=["name as employee", "employee_name", "department", "designation"]
    #     )

    #     existing = {row.employee for row in self.details}
    #     added = 0
    #     for emp in employees:
    #         if emp.employee not in existing:
    #             self.append("details", {
    #                 "employee":      emp.employee,
    #                 "employee_name": emp.employee_name,
    #                 "department":    emp.department,
    #                 "designation":   emp.designation,
    #             })
    #             added += 1

    #     self.total_employees = len(self.details)
    #     self.total_working_days = count_working_days(self.from_date, self.to_date)
    #     self.save()
    #     return {"added": added, "total": len(self.details)}
    @frappe.whitelist()
    def fetch_employees(company=None, department=None, project=None, designation=None):
        """Fetch active employees matching optional filters for bulk-add to shift assignment."""
        filters = {"status": "Active"}
        if company:         filters["company"] = company
        if department:      filters["department"] = department
        if project:         filters["project"] = project
        if designation:     filters["designation"] = designation

        return frappe.get_all(
            "Employee",
            filters=filters,
            fields=["name as employee", "employee_name", "department", "designation"],
            order_by="employee_name asc"
        )
    

    # ── called by JS "Process Attendance" ────────────────────────────────────
    @frappe.whitelist()
    def process_attendance(self):
        """
        Background-safe attendance processing.
        Enqueues a job so it doesn't block the UI.
        """
        if not self.details:
            frappe.throw(_("Please fetch employees first."))
        if not self.from_date or not self.to_date:
            frappe.throw(_("From Date and To Date are required."))

        frappe.db.set_value("Attendance Summary", self.name, "status", "Processing")
        frappe.db.commit()

        frappe.enqueue(
            "zkteco_attendance.zkteco_attendance.doctype.attendance_summary.attendance_summary._process_background",
            summary_name=self.name,
            queue="long",
            timeout=900,
            job_name="att_summary_{}".format(self.name),
        )

        return {"status": "queued", "message": _("Processing started. The page will update when complete.")}


def _process_background(summary_name):
    """Background job: calculate attendance for all employees in the summary."""
    doc = frappe.get_doc("Attendance Summary", summary_name)

    employee_list = [row.employee for row in doc.details]

    checkins_by_employee = fetch_checkins(employee_list, doc.from_date, doc.to_date)

    doc_method         = doc.working_hours_method
    doc_missing_action = doc.missing_checkin_action
    default_shift      = doc.shift_type

    for row in doc.details:
        emp_checkins = checkins_by_employee.get(row.employee, [])
        result = process_employee(
            employee=row.employee,
            from_date=doc.from_date,
            to_date=doc.to_date,
            checkin_list=emp_checkins,
            default_shift_name=default_shift,
            doc_method=doc_method,
            doc_missing_action=doc_missing_action,
        )
        row.working_days        = result["working_days"]
        row.absent_days         = result["absent_days"]
        row.half_days           = result["half_days"]
        row.total_working_hours = result["total_working_hours"]
        row.absent_hours        = result["absent_hours"]
        row.overtime_hours      = result["overtime_hours"]
        row.overtime_days       = result["overtime_days"]
        row.invalid_days        = result["invalid_days"]
        row.manual_review_days  = result["manual_review_days"]
        if result["remarks"]:
            row.remarks = result["remarks"]

    doc.status             = "Completed"
    doc.total_employees    = len(doc.details)
    doc.total_working_days = count_working_days(doc.from_date, doc.to_date)
    doc.total_overtime_hours = round(sum(flt(r.overtime_hours) for r in doc.details), 2)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

