frappe.pages["zk-daily-checkins"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Employee Daily Checkins"),
        single_column: true,
    });

    const state = {
        data: null,
        expanded: new Set(),
    };

    // ── Attendance Summary selector ─────────────────────────────────────────
    const $filterBar = $(`
        <div class="zk-daily-filterbar" style="padding: 12px 0 0 0; max-width: 420px;"></div>
    `).appendTo(page.main);

    const summary_field = frappe.ui.form.make_control({
        df: {
            fieldtype: "Link",
            fieldname: "attendance_summary",
            label: __("Attendance Summary"),
            options: "Attendance Summary",
            placeholder: __("Select an Attendance Summary"),
            change() {
                const val = summary_field.get_value();
                if (val) {
                    frappe.set_route("zk-daily-checkins", val);
                    load_data(val);
                }
            },
        },
        parent: $filterBar,
        render_input: true,
    });
    summary_field.refresh();

    const $body = $(`<div class="zk-daily-body" style="margin-top:18px;"></div>`).appendTo(page.main);

    function render_empty_state() {
        $body.html(`
            <div class="text-muted text-center" style="padding: 60px 0;">
                ${__("Select an Attendance Summary above to view each employee's daily check-ins.")}
            </div>
        `);
    }

    function status_color(status) {
        switch (status) {
            case "Present": return "green";
            case "Half Day": return "orange";
            case "Absent": return "red";
            case "Invalid": return "darkgrey";
            case "Manual Review": return "blue";
            default: return "grey";
        }
    }

    function render_checkin_chips(checkins) {
        if (!checkins || !checkins.length) {
            return `<span class="text-muted">${__("No check-ins")}</span>`;
        }
        return checkins.map(c => {
            const otClass = c.is_overtime ? "zk-chip-ot" : (c.log_type === "IN" ? "zk-chip-in" : "zk-chip-out");
            const label = c.is_overtime ? `${c.log_type} (OT)` : c.log_type;
            return `<span class="zk-chip ${otClass}">${c.time} <b>${label}</b></span>`;
        }).join(" ");
    }

    function render_employee_table(emp) {
        const rows = emp.days.map(d => `
            <tr>
                <td>${frappe.datetime.str_to_user(d.date)}</td>
                <td>${__(d.weekday)}</td>
                <td><span class="indicator-pill ${status_color(d.status)}">${__(d.status)}</span></td>
                <td class="text-right">${d.hours.toFixed(2)}</td>
                <td class="text-right ${d.overtime_hours ? 'text-warning' : ''}">${d.overtime_hours.toFixed(2)}</td>
                <td>${render_checkin_chips(d.checkins)}</td>
            </tr>
        `).join("");

        return `
            <table class="table table-bordered zk-daily-table">
                <thead>
                    <tr>
                        <th style="width:110px">${__("Date")}</th>
                        <th style="width:100px">${__("Day")}</th>
                        <th style="width:110px">${__("Status")}</th>
                        <th style="width:70px" class="text-right">${__("Hours")}</th>
                        <th style="width:70px" class="text-right">${__("OT Hrs")}</th>
                        <th>${__("Check-ins")}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    function render_data(data) {
        if (!data.employees || !data.employees.length) {
            $body.html(`
                <div class="text-muted text-center" style="padding: 40px 0;">
                    ${__("This Attendance Summary has no employees yet. Use 'Fetch Employees' on the Attendance Summary first.")}
                </div>
            `);
            return;
        }

        const header = `
            <div class="zk-daily-header" style="margin-bottom: 14px;">
                <h5 style="margin-bottom:4px;">${frappe.utils.escape_html(data.attendance_summary)}</h5>
                <div class="text-muted">
                    ${frappe.datetime.str_to_user(data.from_date)} &mdash; ${frappe.datetime.str_to_user(data.to_date)}
                    &nbsp;|&nbsp; ${data.company || ""}
                    &nbsp;|&nbsp; ${__("{0} employee(s)", [data.employees.length])}
                </div>
            </div>
        `;

        const cards = data.employees.map((emp, idx) => {
            const isOpen = state.expanded.has(emp.employee);
            const totalOt = emp.days.reduce((s, d) => s + (d.overtime_hours || 0), 0);
            return `
                <div class="zk-emp-card" data-employee="${frappe.utils.escape_html(emp.employee)}">
                    <div class="zk-emp-card-head" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; padding:10px 14px; border:1px solid var(--border-color); border-radius: var(--border-radius); background: var(--card-bg);">
                        <div>
                            <b>${frappe.utils.escape_html(emp.employee_name || emp.employee)}</b>
                            <span class="text-muted" style="margin-left:8px;">${frappe.utils.escape_html(emp.employee)}</span>
                            ${emp.department ? `<span class="text-muted" style="margin-left:8px;">· ${frappe.utils.escape_html(emp.department)}</span>` : ""}
                        </div>
                        <div class="text-muted">
                            ${totalOt ? `<span class="text-warning" style="margin-right:10px;">${__("OT")}: ${totalOt.toFixed(2)}h</span>` : ""}
                            <i class="fa fa-chevron-${isOpen ? "up" : "down"}"></i>
                        </div>
                    </div>
                    <div class="zk-emp-card-body" style="display:${isOpen ? "block" : "none"}; padding-top:8px;">
                        ${render_employee_table(emp)}
                    </div>
                </div>
            `;
        }).join("");

        $body.html(header + `<div class="zk-emp-cards">${cards}</div>`);

        $body.find(".zk-emp-card-head").on("click", function () {
            const $card = $(this).closest(".zk-emp-card");
            const employee = $card.data("employee");
            const $cardBody = $card.find(".zk-emp-card-body");
            const $icon = $(this).find("i.fa");

            if (state.expanded.has(employee)) {
                state.expanded.delete(employee);
                $cardBody.slideUp(150);
                $icon.removeClass("fa-chevron-up").addClass("fa-chevron-down");
            } else {
                state.expanded.add(employee);
                $cardBody.slideDown(150);
                $icon.removeClass("fa-chevron-down").addClass("fa-chevron-up");
            }
        });
    }

    function load_data(attendance_summary) {
        $body.html(`<div class="text-muted text-center" style="padding:40px 0;">${__("Loading…")}</div>`);

        frappe.call({
            method: "zkteco_attendance.zkteco_attendance.page.zk_daily_checkins.zk_daily_checkins.get_data",
            args: { attendance_summary },
            callback(r) {
                if (!r.message) {
                    render_empty_state();
                    return;
                }
                state.data = r.message;
                render_data(state.data);
            },
            error() {
                $body.html(`<div class="text-danger text-center" style="padding:40px 0;">${__("Failed to load data.")}</div>`);
            },
        });
    }

    // ── Route param support: /app/zk-daily-checkins/<Attendance Summary> ────
    const route = frappe.get_route();
    const route_summary = route && route[1];

    if (route_summary) {
        summary_field.set_value(route_summary);
        load_data(route_summary);
    } else {
        render_empty_state();
    }
};
