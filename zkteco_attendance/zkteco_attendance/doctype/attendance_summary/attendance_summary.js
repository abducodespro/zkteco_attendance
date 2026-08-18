// Attendance Summary Form JS
frappe.ui.form.on("Attendance Summary", {

    refresh(frm) {
        frm.trigger("set_status_indicator");

        if (frm.doc.status === "Draft" || frm.doc.status === "Processing") {
            // ── Fetch Employees ──────────────────────────────────────────
            frm.add_custom_button(__("Fetch Employees"), function () {
                if (!frm.doc.from_date || !frm.doc.to_date) {
                    frappe.msgprint(__("Please set From Date and To Date first."));
                    return;
                }
                if (!frm.doc.company) {
                    frappe.msgprint(__("Please select a Company first."));
                    return;
                }
                frm.trigger("show_fetch_dialog");
            }, __("Actions"));
        }

        if (frm.doc.details && frm.doc.details.length > 0) {
            // ── Process Attendance ───────────────────────────────────────
            frm.add_custom_button(__("Process Attendance"), function () {
                frappe.confirm(
                    __("Process attendance for <b>{0}</b> employees from <b>{1}</b> to <b>{2}</b>? This will also calculate overtime where enabled on the shift.",
                        [frm.doc.details.length,
                        frappe.datetime.str_to_user(frm.doc.from_date),
                        frappe.datetime.str_to_user(frm.doc.to_date)]),
                    function () {
                        frm.call({
                            doc: frm.doc,
                            method: "process_attendance",
                            freeze: true,
                            freeze_message: __("Queuing attendance processing..."),
                            callback(r) {
                                if (r.message) {
                                    frappe.show_alert({
                                        message: r.message.message || __("Processing started."),
                                        indicator: "blue"
                                    }, 8);
                                    // Poll for completion
                                    frm.trigger("poll_status");
                                }
                            }
                        });
                    }
                );
            }, __("Actions"));

            // ── View Daily Checkins ────────────────────────────────────────
            frm.add_custom_button(__("View Daily Checkins"), function () {
                frappe.set_route("zk-daily-checkins", frm.doc.name);
            }, __("View"));

            // ── Add Manual Check-in (requires Checkin Editor role) ────────
            if (frappe.user_roles.includes("System Manager")
                || frappe.user_roles.includes("HR Manager")
                || frappe.user_roles.includes("Biometric Device Manager")
                || frappe.user_roles.includes("Checkin Editor")) {
                frm.add_custom_button(__("Add Check-in"), function () {
                    frm.trigger("show_manual_checkin_dialog");
                }, __("Actions"));
            }
        }

        // ── Overtime summary indicator ─────────────────────────────────────
        if (frm.doc.status === "Completed" && frm.doc.total_overtime_hours) {
            const parts = [
                [__("Day"),     frm.doc.total_day_ot_hours],
                [__("Night"),   frm.doc.total_night_ot_hours],
                [__("Weekend"), frm.doc.total_weekend_ot_hours],
                [__("Holiday"), frm.doc.total_holiday_ot_hours],
            ].filter(([, v]) => v).map(([k, v]) => `${k}: ${v} hrs`).join(" | ");

            frm.dashboard.add_comment(
                __("Total Overtime: <b>{0} hrs</b> across {1} employee(s).{2}",
                    [frm.doc.total_overtime_hours, frm.doc.total_employees || 0,
                     parts ? `<br>${parts}` : ""]),
                "orange",
                true
            );
        }
    },

    set_status_indicator(frm) {
        const colors = { "Draft": "gray", "Processing": "orange", "Completed": "green" };
        frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "gray");
    },

    poll_status(frm) {
        // Check every 4 seconds if processing is done
        let polls = 0;
        const interval = setInterval(function () {
            polls++;
            frappe.db.get_value("Attendance Summary", frm.doc.name, "status").then(r => {
                if (r.message.status === "Completed") {
                    clearInterval(interval);
                    frappe.show_alert({ message: __("Processing complete!"), indicator: "green" }, 5);
                    frm.reload_doc();
                } else if (polls > 60) {
                    // Timeout after ~4 minutes
                    clearInterval(interval);
                    frm.reload_doc();
                }
            });
        }, 4000);
    },

    show_manual_checkin_dialog(frm) {
        const employee_options = (frm.doc.details || []).map(r =>
            `${r.employee} — ${r.employee_name || ""}`
        );
        const employee_map = {};
        (frm.doc.details || []).forEach(r => { employee_map[r.employee] = r.employee_name; });
        const emp_keys = Object.keys(employee_map);

        const d = new frappe.ui.Dialog({
            title: __("Add Manual Check-in"),
            fields: [
                {
                    fieldtype: "Link",
                    fieldname: "employee",
                    label: __("Employee"),
                    options: "Employee",
                    get_query() {
                        return { filters: { name: ["in", emp_keys] } };
                    },
                    reqd: 1,
                },
                { fieldtype: "Column Break" },
                {
                    fieldtype: "Select",
                    fieldname: "log_type",
                    label: __("Log Type"),
                    options: "IN\nOUT",
                    default: "IN",
                    reqd: 1,
                },
                { fieldtype: "Section Break" },
                {
                    fieldtype: "Date",
                    fieldname: "checkin_date",
                    label: __("Date"),
                    default: frm.doc.from_date,
                    reqd: 1,
                },
                { fieldtype: "Column Break" },
                {
                    fieldtype: "Time",
                    fieldname: "checkin_time",
                    label: __("Time"),
                    default: "08:00:00",
                    reqd: 1,
                },
            ],
            primary_action_label: __("Save Check-in"),
            primary_action(vals) {
                if (!vals.employee || !vals.checkin_date || !vals.checkin_time) {
                    frappe.msgprint(__("All fields are required."));
                    return;
                }
                const checkin_time = vals.checkin_date + " " + vals.checkin_time;
                frm.call({
                    doc: frm.doc,
                    method: "save_manual_checkin",
                    args: {
                        employee:     vals.employee,
                        checkin_time: checkin_time,
                        log_type:     vals.log_type,
                    },
                    freeze: true,
                    freeze_message: __("Saving check-in…"),
                    callback(r) {
                        d.hide();
                        if (r.message) {
                            frappe.show_alert({
                                message: __("Check-in {0} for {1} at {2}.",
                                    [r.message.action, vals.employee, checkin_time]),
                                indicator: "green",
                            }, 6);
                        }
                    },
                });
            },
        });
        d.show();
    },

    show_fetch_dialog(frm) {
        const d = new frappe.ui.Dialog({
            title: __("Fetch Employees"),
            fields: [
                {
                    label: __("Filter By"),
                    fieldname: "filter_by",
                    fieldtype: "Select",
                    options: ["All Active Employees", "Department", "Designation", "Project"],
                    default: "All Active Employees",
                    onchange() {
                        const v = d.get_value("filter_by");
                        d.set_df_property("department", "hidden", v !== "Department");
                        d.set_df_property("designation", "hidden", v !== "Designation");
                        d.set_df_property("project", "hidden", v !== "Project");
                    }
                },
                { label: __("Department"), fieldname: "department", fieldtype: "Link", options: "Department", hidden: 1 },
                { label: __("Designation"), fieldname: "designation", fieldtype: "Link", options: "Designation", hidden: 1 },
                { label: __("Project"), fieldname: "project", fieldtype: "Link", options: "Project", hidden: 1 },
            ],
            primary_action_label: __("Fetch"),
            primary_action(values) {
                const filters = {
                    company: frm.doc.company,
                    status: "Active",
                };
                if (values.filter_by === "Department" && values.department) {
                    filters.department = values.department;
                }
                if (values.filter_by === "Designation" && values.designation) {
                    filters.designation = values.designation;
                }
                if (values.filter_by === "Project" && values.project) {
                    filters.project = values.project;
                }

                frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "Employee",
                        filters: filters,
                        fields: ["name", "employee_name", "department", "designation"],
                        limit_page_length: 5000,
                        order_by: "employee_name asc",
                    },
                    freeze: true,
                    freeze_message: __("Fetching employees..."),
                    callback(r) {
                        d.hide();

                        const emps = r.message || [];
                        if (!emps.length) {
                            frappe.msgprint(__("No employees found matching those filters."));
                            return;
                        }

                        const existing = new Set((frm.doc.details || []).map(row => row.employee));
                        let added = 0;

                        emps.forEach(emp => {
                            if (!existing.has(emp.name)) {
                                frm.add_child("details", {
                                    employee: emp.name,
                                    employee_name: emp.employee_name,
                                    department: emp.department,
                                    designation: emp.designation,
                                });
                                existing.add(emp.name);
                                added++;
                            }
                        });

                        frm.refresh_field("details");

                        frm.doc.total_employees = frm.doc.details.length;
                        frm.refresh_field("total_employees");

                        frappe.show_alert({
                            message: __("{0} employee(s) added. Total: {1}", [added, frm.doc.details.length]),
                            indicator: "green"
                        }, 5);
                    }
                });
            }
        });
        d.show();
    }
});
