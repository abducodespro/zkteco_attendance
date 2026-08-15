// ZKTeco Attendance — Employee Daily Checkins Page
// Shows a per-employee, per-day checkin breakdown.
// Supports standalone date-range mode (no Attendance Summary required)
// and navigation-from-summary mode.

frappe.pages["zk-daily-checkins"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Employee Daily Checkins"),
        single_column: true,
    });

    const state = {
        data:             null,
        expanded:         new Set(),
        from_date:        null,
        to_date:          null,
        attendance_summary: null,
        employee_list:    [],
    };

    // ── Filter bar ────────────────────────────────────────────────────────
    const $filterWrap = $(`
        <div class="zk-daily-filterbar" style="padding:14px 0 0 0;">
            <div class="row">
                <div class="col-sm-3" id="zk-fd"></div>
                <div class="col-sm-3" id="zk-td"></div>
                <div class="col-sm-4" id="zk-summary-wrap">
                    <div id="zk-summary"></div>
                </div>
                <div class="col-sm-2" style="display:flex;align-items:flex-end;padding-bottom:4px;">
                    <button class="btn btn-primary btn-sm" id="zk-load-btn">${__("Load")}</button>
                    &nbsp;
                    <button class="btn btn-default btn-sm" id="zk-clear-btn">${__("Clear")}</button>
                </div>
            </div>
        </div>
    `).appendTo(page.main);

    // From Date control
    const from_ctrl = frappe.ui.form.make_control({
        df: { fieldtype: "Date", fieldname: "from_date", label: __("From Date") },
        parent: $filterWrap.find("#zk-fd"),
        render_input: true,
    });
    from_ctrl.refresh();

    // To Date control
    const to_ctrl = frappe.ui.form.make_control({
        df: { fieldtype: "Date", fieldname: "to_date", label: __("To Date") },
        parent: $filterWrap.find("#zk-td"),
        render_input: true,
    });
    to_ctrl.refresh();

    // Attendance Summary link (optional — pre-fills dates + employees)
    const summary_ctrl = frappe.ui.form.make_control({
        df: {
            fieldtype: "Link",
            fieldname: "attendance_summary",
            label: __("From Attendance Summary (optional)"),
            options: "Attendance Summary",
            change() {
                const val = summary_ctrl.get_value();
                if (!val) return;
                frappe.db.get_doc("Attendance Summary", val).then(doc => {
                    from_ctrl.set_value(doc.from_date);
                    to_ctrl.set_value(doc.to_date);
                    state.attendance_summary = val;
                    state.employee_list = (doc.details || []).map(r => r.employee);
                });
            },
        },
        parent: $filterWrap.find("#zk-summary"),
        render_input: true,
    });
    summary_ctrl.refresh();

    const $body = $(`<div class="zk-daily-body" style="margin-top:18px;"></div>`).appendTo(page.main);

    // ── Delegated handlers (bound ONCE — $body persists across renders) ──
    // These must NOT be re-bound inside render_data(), otherwise each Load
    // stacks another copy and a single click opens multiple dialogs.
    $body.on("click", ".zk-add-checkin", function () {
        const emp     = $(this).data("employee");
        const date    = $(this).data("date");
        const summary = $(this).data("summary");
        show_checkin_dialog({ employee: emp, date, summary, mode: "add" });
    });

    $body.on("click", ".zk-edit-checkin", function (e) {
        e.stopPropagation();
        const emp     = $(this).data("employee");
        const date    = $(this).data("date");
        const time    = $(this).data("time");
        const logtype = $(this).data("logtype");
        const summary = $(this).data("summary");
        const checkin = $(this).data("checkin-name");
        show_checkin_dialog({ employee: emp, date, time, logtype, summary, checkin_name: checkin, mode: "edit" });
    });

    // ── Load / Clear buttons ──────────────────────────────────────────────
    $filterWrap.find("#zk-load-btn").on("click", () => trigger_load());
    $filterWrap.find("#zk-clear-btn").on("click", () => {
        from_ctrl.set_value("");
        to_ctrl.set_value("");
        summary_ctrl.set_value("");
        state.attendance_summary = null;
        state.employee_list = [];
        state.data = null;
        render_empty_state();
    });

    // ── Helpers ───────────────────────────────────────────────────────────
    function render_empty_state(msg) {
        $body.html(`<div class="text-muted text-center" style="padding:60px 0;">
            ${msg || __("Set a date range and click Load to view daily check-ins.")}
        </div>`);
    }

    function status_color(status) {
        const map = { Present: "green", "Half Day": "orange", Absent: "red",
                      Invalid: "darkgrey", "Manual Review": "blue" };
        return map[status] || "grey";
    }

    function render_checkin_chips(checkins, emp, date, summary_name) {
        const summary_attr = summary_name ? frappe.utils.escape_html(summary_name) : "";
        const add_btn = (with_label) => `
            <button class="btn btn-xs btn-default zk-add-checkin"
                    data-employee="${frappe.utils.escape_html(emp)}"
                    data-date="${date}"
                    data-summary="${summary_attr}"
                    style="margin-left:6px;">
                <i class="fa fa-plus"></i>${with_label ? ` ${__("Add")}` : ""}
            </button>`;

        if (!checkins || !checkins.length) {
            return `<span class="text-muted">${__("No check-ins")}</span>${add_btn(true)}`;
        }

        const chips = checkins.map((c, idx) => {
            const otClass = c.is_overtime
                ? "zk-chip-ot"
                : (c.log_type === "IN" ? "zk-chip-in" : "zk-chip-out");
            const label = c.is_overtime ? `${c.log_type} (OT)` : c.log_type;

            let manualBadge = "";
            let editBtn     = "";
            if (c.manually_edited) {
                const tip = c.edited_by
                    ? `${__("Edited by")} ${frappe.utils.escape_html(c.edited_by)}${c.edited_at ? " @ " + c.edited_at.substring(0,16) : ""}`
                    : __("Manually added/edited");
                manualBadge = `<span class="zk-manual-badge" title="${tip}">✎</span>`;
            }
            editBtn = `<span class="zk-edit-checkin" title="${__("Edit")}"
                            data-employee="${frappe.utils.escape_html(emp)}"
                            data-date="${date}"
                            data-time="${c.time}"
                            data-logtype="${c.log_type}"
                            data-idx="${idx}"
                            data-checkin-name="${frappe.utils.escape_html(c.name || "")}"
                            data-summary="${summary_attr}"
                            style="cursor:pointer;margin-left:4px;opacity:0.6;">✎</span>`;
            return `<span class="zk-chip ${otClass}">${c.time} <b>${label}</b>${manualBadge}${editBtn}</span>`;
        }).join(" ");

        return chips + add_btn(false);
    }

    function render_employee_table(emp, summary_name) {
        const rows = emp.days.map(d => {
            const satMark = d.is_saturday
                ? `<span class="text-muted" style="font-size:0.7rem;margin-left:4px;">SAT</span>`
                : "";
            const otCell = (d.day_ot_hours || d.night_ot_hours)
                ? `<span title="${__("Day OT")}: ${(d.day_ot_hours||0).toFixed(2)}h | ${__("Night OT")}: ${(d.night_ot_hours||0).toFixed(2)}h">
                       ${(d.overtime_hours||0).toFixed(2)}
                   </span>`
                : (d.overtime_hours || 0).toFixed(2);
            return `
                <tr>
                    <td>${frappe.datetime.str_to_user(d.date)}${satMark}</td>
                    <td>${__(d.weekday)}</td>
                    <td><span class="indicator-pill ${status_color(d.status)}">${__(d.status)}</span></td>
                    <td class="text-right">${(d.hours||0).toFixed(2)}</td>
                    <td class="text-right ${d.overtime_hours ? 'text-warning' : ''}">${otCell}</td>
                    <td>${render_checkin_chips(d.checkins, emp.employee, d.date, summary_name)}</td>
                </tr>`;
        }).join("");

        return `
            <table class="table table-bordered zk-daily-table">
                <thead>
                    <tr>
                        <th style="width:115px">${__("Date")}</th>
                        <th style="width:95px">${__("Day")}</th>
                        <th style="width:115px">${__("Status")}</th>
                        <th style="width:70px" class="text-right">${__("Hours")}</th>
                        <th style="width:75px" class="text-right">${__("OT Hrs")}</th>
                        <th>${__("Check-ins")}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function render_data(data) {
        if (!data.employees || !data.employees.length) {
            render_empty_state(__("No employees found for the selected range."));
            return;
        }

        const header = `
            <div class="zk-daily-header" style="margin-bottom:14px;">
                <div class="text-muted">
                    <b>${frappe.datetime.str_to_user(data.from_date)}</b>
                    &mdash;
                    <b>${frappe.datetime.str_to_user(data.to_date)}</b>
                    ${data.company ? "&nbsp;|&nbsp;" + frappe.utils.escape_html(data.company) : ""}
                    &nbsp;|&nbsp; ${__("{0} employee(s)", [data.employees.length])}
                    ${data.attendance_summary
                        ? `&nbsp;|&nbsp; <a href="/app/attendance-summary/${encodeURIComponent(data.attendance_summary)}">${frappe.utils.escape_html(data.attendance_summary)}</a>`
                        : ""}
                </div>
            </div>`;

        const cards = data.employees.map(emp => {
            const isOpen   = state.expanded.has(emp.employee);
            const totalOt  = (emp.days||[]).reduce((s,d) => s+(d.overtime_hours||0), 0);
            const dayOt    = (emp.days||[]).reduce((s,d) => s+(d.day_ot_hours||0), 0);
            const nightOt  = (emp.days||[]).reduce((s,d) => s+(d.night_ot_hours||0), 0);
            const otLabel  = totalOt
                ? `<span class="text-warning" style="margin-right:10px;" title="${__("Day OT")}: ${dayOt.toFixed(2)}h | ${__("Night OT")}: ${nightOt.toFixed(2)}h">
                       ${__("OT")}: ${totalOt.toFixed(2)}h
                   </span>`
                : "";
            return `
                <div class="zk-emp-card" data-employee="${frappe.utils.escape_html(emp.employee)}" style="margin-bottom:10px;">
                    <div class="zk-emp-card-head" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--border-radius);background:var(--card-bg);">
                        <div>
                            <b>${frappe.utils.escape_html(emp.employee_name||emp.employee)}</b>
                            <span class="text-muted" style="margin-left:8px;">${frappe.utils.escape_html(emp.employee)}</span>
                            ${emp.department ? `<span class="text-muted" style="margin-left:8px;">· ${frappe.utils.escape_html(emp.department)}</span>` : ""}
                        </div>
                        <div class="text-muted">${otLabel}<i class="fa fa-chevron-${isOpen?"up":"down"}"></i></div>
                    </div>
                    <div class="zk-emp-card-body" style="display:${isOpen?"block":"none"};padding-top:8px;">
                        ${render_employee_table(emp, data.attendance_summary)}
                    </div>
                </div>`;
        }).join("");

        $body.html(header + `<div class="zk-emp-cards">${cards}</div>`);

        // Expand/collapse
        $body.find(".zk-emp-card-head").on("click", function () {
            const $card = $(this).closest(".zk-emp-card");
            const employee = $card.data("employee");
            const $cb = $card.find(".zk-emp-card-body");
            const $ic = $(this).find("i.fa");
            if (state.expanded.has(employee)) {
                state.expanded.delete(employee);
                $cb.slideUp(150);
                $ic.removeClass("fa-chevron-up").addClass("fa-chevron-down");
            } else {
                state.expanded.add(employee);
                $cb.slideDown(150);
                $ic.removeClass("fa-chevron-down").addClass("fa-chevron-up");
            }
        });
    }

    // ── Manual checkin dialog ─────────────────────────────────────────────
    function show_checkin_dialog({ employee, date, time, logtype, summary, checkin_name, mode }) {
        const defaultTime = time || "08:00:00";
        const d = new frappe.ui.Dialog({
            title: mode === "edit" ? __("Edit Check-in") : __("Add Check-in"),
            fields: [
                { fieldtype: "Link", fieldname: "employee", label: __("Employee"),
                  options: "Employee", default: employee, read_only: 1 },
                { fieldtype: "Date", fieldname: "checkin_date", label: __("Date"),
                  default: date, reqd: 1 },
                { fieldtype: "Time", fieldname: "checkin_time", label: __("Time"),
                  default: defaultTime, reqd: 1 },
                { fieldtype: "Select", fieldname: "log_type", label: __("Log Type"),
                  options: "IN\nOUT", default: logtype || "IN", reqd: 1 },
            ],
            primary_action_label: mode === "edit" ? __("Update") : __("Save"),
            primary_action(vals) {
                if (!vals.checkin_date || !vals.checkin_time) {
                    frappe.msgprint(__("Date and Time are required."));
                    return;
                }
                const checkin_time = vals.checkin_date + " " + vals.checkin_time;
                frappe.call({
                    method: "zkteco_attendance.zkteco_attendance.page.zk_daily_checkins.zk_daily_checkins.save_manual_checkin",
                    args: {
                        attendance_summary: summary || null,
                        employee:           vals.employee,
                        checkin_time,
                        log_type:           vals.log_type,
                        checkin_name:       checkin_name || null,
                    },
                    freeze: true,
                    freeze_message: __("Saving…"),
                    callback(r) {
                        d.hide();
                        if (r.message) {
                            frappe.show_alert({
                                message: r.message.action === "created"
                                    ? __("Check-in added successfully.")
                                    : __("Check-in updated successfully."),
                                indicator: "green",
                            }, 4);
                            trigger_load();
                        }
                    },
                });
            },
        });
        d.show();
    }

    // ── Load logic ────────────────────────────────────────────────────────
    function trigger_load() {
        const fd = from_ctrl.get_value();
        const td = to_ctrl.get_value();

        if (!fd || !td) {
            frappe.msgprint(__("Please set both From Date and To Date."));
            return;
        }

        $body.html(`<div class="text-muted text-center" style="padding:40px 0;">${__("Loading…")}</div>`);

        frappe.call({
            method: "zkteco_attendance.zkteco_attendance.page.zk_daily_checkins.zk_daily_checkins.get_data",
            args: {
                attendance_summary: state.attendance_summary || null,
                from_date:          fd,
                to_date:            td,
                employee_list:      state.employee_list.length ? JSON.stringify(state.employee_list) : null,
            },
            callback(r) {
                if (!r.message) { render_empty_state(); return; }
                state.data = r.message;
                render_data(state.data);
            },
            error() {
                $body.html(`<div class="text-danger text-center" style="padding:40px 0;">${__("Failed to load data.")}</div>`);
            },
        });
    }

    // ── Route initialisation ──────────────────────────────────────────────
    // Route: /app/zk-daily-checkins/<Attendance Summary name>
    // or:    /app/zk-daily-checkins  (standalone)
    const route        = frappe.get_route();
    const route_param  = route && route[1];

    if (route_param && route_param !== "zk-daily-checkins") {
        // Navigated from Attendance Summary — pre-fill everything from it
        state.attendance_summary = route_param;
        summary_ctrl.set_value(route_param);
        frappe.db.get_doc("Attendance Summary", route_param).then(doc => {
            from_ctrl.set_value(doc.from_date);
            to_ctrl.set_value(doc.to_date);
            state.employee_list = (doc.details || []).map(r => r.employee);
            trigger_load();
        });
    } else {
        // Standalone — default to current month
        const today       = frappe.datetime.get_today();
        const first_of_month = today.substring(0, 8) + "01";
        from_ctrl.set_value(first_of_month);
        to_ctrl.set_value(today);
        render_empty_state();
    }
};
