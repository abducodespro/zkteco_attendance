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
        biometric_device: null,
        filter_employee:  null,
        can_edit_checkins: frappe.user_roles.includes("Checkin Editor"),
    };

    // ── Filter bar ────────────────────────────────────────────────────────
    const $filterWrap = $(`
        <div class="zk-daily-filterbar" style="padding:14px 0 0 0;">
            <div class="row" style="margin-bottom:8px;">
                <div class="col-sm-2" id="zk-fd"></div>
                <div class="col-sm-2" id="zk-td"></div>
                <div class="col-sm-3" id="zk-summary-wrap">
                    <div id="zk-summary"></div>
                </div>
                <div class="col-sm-3" id="zk-device-wrap">
                    <div id="zk-device"></div>
                </div>
                <div class="col-sm-2" id="zk-emp-wrap">
                    <div id="zk-emp"></div>
                </div>
            </div>
            <div class="row">
                <div class="col-sm-12" style="display:flex;align-items:center;padding-top:4px;">
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
            label: __("Attendance Summary (optional)"),
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

    // Biometric Device filter
    const device_ctrl = frappe.ui.form.make_control({
        df: {
            fieldtype: "Link",
            fieldname: "biometric_device",
            label: __("Biometric Device"),
            options: "Biometric Device",
            change() {
                state.biometric_device = device_ctrl.get_value();
            },
        },
        parent: $filterWrap.find("#zk-device"),
        render_input: true,
    });
    device_ctrl.refresh();

    // Employee filter
    const emp_ctrl = frappe.ui.form.make_control({
        df: {
            fieldtype: "Link",
            fieldname: "filter_employee",
            label: __("Employee"),
            options: "Employee",
            change() {
                state.filter_employee = emp_ctrl.get_value();
            },
        },
        parent: $filterWrap.find("#zk-emp"),
        render_input: true,
    });
    emp_ctrl.refresh();

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
        const ot      = $(this).data("is-overtime");
        show_checkin_dialog({ employee: emp, date, time, logtype, summary, checkin_name: checkin, is_overtime: ot, mode: "edit" });
    });

    $body.on("click", ".zk-ignore-checkin", function (e) {
        e.stopPropagation();
        const $el = $(this);
        const checkinName = $el.data("checkin-name");
        if (!checkinName) return;
        frappe.confirm(
            __($el.data("ignored") ? "Unignore this checkin? It will be included in attendance processing again." : "Ignore this checkin? It will be excluded from attendance processing."),
            () => {
                frappe.call({
                    method: "zkteco_attendance.zkteco_attendance.page.zk_daily_checkins.zk_daily_checkins.toggle_ignore_checkin",
                    args: { checkin_name: checkinName },
                    freeze: true,
                    freeze_message: __($el.data("ignored") ? "Unignoring…" : "Ignoring…"),
                    callback(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: r.message.action === "ignored"
                                    ? __("Checkin ignored successfully.")
                                    : __("Checkin unignored successfully."),
                                indicator: r.message.action === "ignored" ? "orange" : "green",
                            }, 4);
                            trigger_load();
                        }
                    },
                });
            },
            () => {}
        );
    });

    // ── Load / Clear buttons ──────────────────────────────────────────────
    $filterWrap.find("#zk-load-btn").on("click", () => trigger_load());
    $filterWrap.find("#zk-clear-btn").on("click", () => {
        from_ctrl.set_value("");
        to_ctrl.set_value("");
        summary_ctrl.set_value("");
        device_ctrl.set_value("");
        emp_ctrl.set_value("");
        state.attendance_summary = null;
        state.employee_list = [];
        state.biometric_device = null;
        state.filter_employee  = null;
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
                      Invalid: "darkgrey", "Manual Review": "blue",
                      Holiday: "purple", "Weekly_Off": "grey" };
        return map[status] || "grey";
    }

    // OT breakdown chips — Day / Night / Weekend / Holiday overtime
    function ot_cell(d) {
        const chips = [];
        if (d.day_ot_hours)        chips.push(`<span class="zk-ot-chip zk-ot-day" title="${__("Day OT (after shift end)")}" style="border: 1px solid #38684e; background-color: #8bf8c2; border-radius: 4px; padding: 2px 4px">D ${(d.day_ot_hours||0).toFixed(1)}</span>`);
        if (d.night_ot_hours)      chips.push(`<span class="zk-ot-chip zk-ot-night" title="${__("Night OT (night window)")}" style="border: 1px solid #5d6838; background-color: #d6f88b; border-radius: 4px; padding: 2px 4px">N ${(d.night_ot_hours||0).toFixed(1)}</span>`);
        if (d.weekend_ot_hours)    chips.push(`<span class="zk-ot-chip zk-ot-weekend" title="${__("Weekend OT (weekly rest day)")}" style="border: 1px solid #683848; background-color: #f88bc5; border-radius: 4px; padding: 2px 4px;">W ${(d.weekend_ot_hours||0).toFixed(1)}</span>`);
        if (d.holiday_ot_hours)    chips.push(`<span class="zk-ot-chip zk-ot-holiday" title="${__("Holiday OT (public holiday)")}" style="border: 1px solid #4a3868; background-color: #bc8bf8; border-radius: 4px; padding: 2px 4px;">H ${(d.holiday_ot_hours||0).toFixed(1)}</span>`);
        return chips.length ? chips.join(" ") : `<span class="text-muted">—</span>`;
    }

    // Late entry / early exit badges (beyond the shift's grace periods)
    function grace_badges(d) {
        const badges = [];
        if (d.is_late) {
            badges.push(`<span class="zk-grace-badge" title="${__("Late entry")}: ${d.late_minutes} ${__("min beyond grace")}" style="border:1px solid #b07a2a;background-color:#ffd98b;color:#7a5200;border-radius:4px;padding:1px 4px;margin-left:4px;font-size:0.7rem;">${__("L Entry")}</span>`);
        }
        if (d.is_early_exit) {
            badges.push(`<span class="zk-grace-badge" title="${__("Early exit")}: ${d.early_minutes} ${__("min beyond grace")}" style="border:1px solid #b07a2a;background-color:#ffd98b;color:#7a5200;border-radius:4px;padding:1px 4px;margin-left:4px;font-size:0.7rem;">${__("E Exit")}</span>`);
        }
        return badges.join("");
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
            if (!state.can_edit_checkins) {
                return `<span class="text-muted">${__("No check-ins")}</span>`;
            }
            return `<span class="text-muted">${__("No check-ins")}</span>${add_btn(true)}`;
        }

        const chips = checkins.map((c, idx) => {
            const otClass = c.is_overtime
                ? "zk-chip-ot"
                : (c.log_type === "IN" ? "zk-chip-in" : "zk-chip-out");
            const label = c.is_overtime ? `${c.log_type} (OT)` : c.log_type;
            const ignoredClass = c.ignored ? "zk-chip-ignored" : "";

            let manualBadge = "";
            let editBtn     = "";
            let ignoreBtn   = "";
            if (c.manually_edited) {
                const tip = c.edited_by
                    ? `${__("Edited by")} ${frappe.utils.escape_html(c.edited_by)}${c.edited_at ? " @ " + c.edited_at.substring(0,16) : ""}`
                    : __("Manually added/edited");
                manualBadge = `<span class="zk-manual-badge" title="${tip}">✎</span>`;
            }
            if (c.ignored) {
                manualBadge = `<span class="zk-ignored-badge" title="${__("This checkin is ignored — excluded from attendance processing")}">⊘</span>`;
            }
            if (state.can_edit_checkins) {
                editBtn = `<span class="zk-edit-checkin" title="${__("Edit")}"
                                data-employee="${frappe.utils.escape_html(emp)}"
                                data-date="${date}"
                                data-time="${c.time}"
                                data-logtype="${c.log_type}"
                                data-idx="${idx}"
                                data-checkin-name="${frappe.utils.escape_html(c.name || "")}"
                                data-is-overtime="${c.is_overtime ? 1 : 0}"
                                data-summary="${summary_attr}"
                                style="cursor:pointer;margin-left:4px;opacity:0.6;">✎</span>`;
                ignoreBtn = `<span class="zk-ignore-checkin" title="${c.ignored ? __("Unignore (include in attendance)") : __("Ignore (exclude from attendance)")}"
                                data-checkin-name="${frappe.utils.escape_html(c.name || "")}"
                                data-ignored="${c.ignored ? 1 : 0}"
                                style="cursor:pointer;margin-left:4px;opacity:0.6;">${c.ignored ? "⊘" : "○"}</span>`;
            }
            return `<span class="zk-chip ${otClass} ${ignoredClass}">${c.time} <b>${label}</b>${manualBadge} ${editBtn} ${ignoreBtn}</span>`;
        }).join(" ");

        if (!state.can_edit_checkins) {
            return chips;
        }
        return chips + add_btn(false);
    }

    function render_employee_table(emp, summary_name) {
        const rows = emp.days.map(d => {
            const dayMark = d.is_holiday
                ? `<span class="zk-day-mark zk-day-holiday" title="${__("Public Holiday")}">HOL</span>`
                : d.is_weekend
                    ? `<span class="zk-day-mark zk-day-weekend" title="${__("Weekly Rest Day")}">SUN</span>`
                    : d.is_saturday
                        ? `<span class="zk-day-mark" title="${__("Saturday")}">SAT</span>`
                        : "";
            return `
                <tr>
                    <td style="border: 1px solid #385068;">${frappe.datetime.str_to_user(d.date)}${dayMark}</td>
                    <td style="border: 1px solid #385068;">${__(d.weekday)}</td>
                    <td style="border: 1px solid #385068;"><span class="indicator-pill ${status_color(d.status)}">${__(d.status)}</span>${grace_badges(d)}</td>
                    <td class="text-right" style="border: 1px solid #385068;">${(d.hours||0).toFixed(2)}</td>
                    <td class="text-right ${d.overtime_hours ? 'text-warning' : ''}" style="border: 1px solid #385068;">${ot_cell(d)}</td>
                    <td style="border: 1px solid #385068;">${render_checkin_chips(d.checkins, emp.employee, d.date, summary_name)}</td>
                </tr>`;
        }).join("");

        return `
            <table class="table table-bordered zk-daily-table">
                <thead>
                    <tr>
                        <th style="width:120px; border: 1px solid #385068; background-color: #8bc2f8;">${__("Date")}</th>
                        <th style="width:90px; border: 1px solid #385068; background-color: #8bc2f8;">${__("Day")}</th>
                        <th style="width:120px; border: 1px solid #385068; background-color: #8bc2f8;">${__("Status")}</th>
                        <th style="width:70px; border: 1px solid #385068; background-color: #8bc2f8;" class="text-right">${__("Hours")}</th>
                        <th style="width:160px; border: 1px solid #385068; background-color: #8bc2f8;" class="text-right">${__("OT Breakdown")}</th>
                        <th style="border: 1px solid #385068; background-color: #8bc2f8;">${__("Check-ins")}</th>
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
                <div class="text-muted" style="font-size:0.72rem;margin-top:4px;">
                    ${__("OT legend")}: <span class="zk-ot-chip zk-ot-day">D ${__("Day")}</span>
                    <span class="zk-ot-chip zk-ot-night">N ${__("Night")}</span>
                    <span class="zk-ot-chip zk-ot-weekend">W ${__("Weekend")}</span>
                    <span class="zk-ot-chip zk-ot-holiday">H ${__("Holiday")}</span>
                </div>
            </div>`;

        const cards = data.employees.map(emp => {
            const isOpen   = state.expanded.has(emp.employee);
            const totalOt  = (emp.days||[]).reduce((s,d) => s+(d.overtime_hours||0), 0);
            const dayOt    = (emp.days||[]).reduce((s,d) => s+(d.day_ot_hours||0), 0);
            const nightOt  = (emp.days||[]).reduce((s,d) => s+(d.night_ot_hours||0), 0);
            const weekendOt = (emp.days||[]).reduce((s,d) => s+(d.weekend_ot_hours||0), 0);
            const holidayOt = (emp.days||[]).reduce((s,d) => s+(d.holiday_ot_hours||0), 0);
            const otLabel  = totalOt
                ? `<span class="text-warning" style="margin-right:10px;" title="${__("Day OT")}: ${dayOt.toFixed(2)}h | ${__("Night OT")}: ${nightOt.toFixed(2)}h | ${__("Weekend OT")}: ${weekendOt.toFixed(2)}h | ${__("Holiday OT")}: ${holidayOt.toFixed(2)}h">
                       ${__("OT")}: ${totalOt.toFixed(2)}h
                   </span>`
                : "";

            const deviceInfo = [];
            if (emp.zk_biometric_device) {
                deviceInfo.push(`<span class="text-muted" title="${__("Biometric Device")}" style="margin-left:8px;font-size:0.78rem;">📱 ${frappe.utils.escape_html(emp.zk_biometric_device)}</span>`);
            }
            if (emp.attendance_device_id) {
                deviceInfo.push(`<span class="text-muted" title="${__("Device ID")}" style="margin-left:8px;font-size:0.78rem;">🆔 ${frappe.utils.escape_html(emp.attendance_device_id)}</span>`);
            }

            return `
                <div class="zk-emp-card" data-employee="${frappe.utils.escape_html(emp.employee)}" style="margin-bottom:10px;">
                    <div class="zk-emp-card-head" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--border-radius);background:var(--card-bg);">
                        <div>
                            <b>${frappe.utils.escape_html(emp.employee_name||emp.employee)}</b>
                            <span class="text-muted" style="margin-left:8px;">${frappe.utils.escape_html(emp.employee)}</span>
                            ${emp.department ? `<span class="text-muted" style="margin-left:8px;">· ${frappe.utils.escape_html(emp.department)}</span>` : ""}
                            ${deviceInfo.join("")}
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
    function render_shift_html($wrapper, s) {
        if (!s) {
            $wrapper.html(
                `<div class="text-muted" style="padding:4px 0 8px;font-size:0.82rem;">${__("No shift assigned")}</div>`
            );
            return;
        }
        $wrapper.html(`
            <div style="background:var(--card-bg);border:1px solid var(--border-color);border-radius:6px;padding:8px 12px;margin-bottom:10px;font-size:0.82rem;">
                <b>${__("Shift")}:</b> ${frappe.utils.escape_html(s.name)}
                &nbsp;|&nbsp; <b>${__("Time")}:</b> ${s.start_time} – ${s.end_time}
                ${s.is_night_shift ? `<span class="text-warning"> (${__("Night Shift")})</span>` : ""}
                &nbsp;|&nbsp; <b>${__("Full Day")}:</b> ${s.full_day_hours}h
                &nbsp;|&nbsp; <b>${__("Half Day")}:</b> ${s.half_day_hours}h
                ${s.lunch_break_hours ? `&nbsp;|&nbsp; <b>${__("Lunch")}:</b> ${s.lunch_break_hours}h` : ""}
                <br>
                <b>${__("Standard Hours")}:</b> ${s.standard_working_hours}h
                &nbsp;|&nbsp; <b>${__("Saturday Mode")}:</b> ${s.saturday_mode}${s.saturday_mode === "Half Day" ? ` (${s.saturday_half_day_hours}h)` : ""}
                &nbsp;|&nbsp; <b>${__("OT")}:</b> ${s.enable_overtime ? s.overtime_calculation_method : __("Disabled")}
            </div>`);
    }

    function show_checkin_dialog({ employee, date, time, logtype, summary, checkin_name, is_overtime, mode }) {
        const defaultTime = time || "08:00:00";
        const isOT = is_overtime ? 1 : 0;

        function get_shift_wrapper(dlg) {
            // Prefer fields_dict, fall back to direct DOM query
            if (dlg.fields_dict && dlg.fields_dict.shift_info && dlg.fields_dict.shift_info.$wrapper) {
                return dlg.fields_dict.shift_info.$wrapper;
            }
            return dlg.$wrapper.find('.frappe-control[data-fieldname="shift_info"]');
        }

        function fetch_and_render_shift(dlg, emp, work_date) {
            const $wrapper = get_shift_wrapper(dlg);
            if (!$wrapper || !$wrapper.length) return;
            frappe.call({
                method: "zkteco_attendance.zkteco_attendance.page.zk_daily_checkins.zk_daily_checkins.get_employee_shift_info",
                args: { employee: emp, work_date: work_date },
                callback(r) {
                    const $w = get_shift_wrapper(dlg);
                    if ($w && $w.length) render_shift_html($w, r.message);
                },
            });
        }

        const d = new frappe.ui.Dialog({
            title: mode === "edit" ? __("Edit Check-in") : __("Add Check-in"),
            fields: [
                { fieldtype: "HTML", fieldname: "shift_info" },
                { fieldtype: "Link", fieldname: "employee", label: __("Employee"),
                  options: "Employee", default: employee, read_only: 1 },
                { fieldtype: "Date", fieldname: "checkin_date", label: __("Date"),
                  default: date, reqd: 1 },
                { fieldtype: "Time", fieldname: "checkin_time", label: __("Time"),
                  default: defaultTime, reqd: 1 },
                { fieldtype: "Select", fieldname: "log_type", label: __("Log Type"),
                  options: "IN\nOUT", default: logtype || "IN", reqd: 1 },
                { fieldtype: "Check", fieldname: "is_overtime", label: __("Is Overtime"),
                  default: isOT, description: __("Mark this punch as an overtime punch") },
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
                        is_overtime:        vals.is_overtime ? 1 : 0,
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
        // Fetch shift info after dialog DOM is fully rendered
        frappe.after_ajax(() => {
            setTimeout(() => fetch_and_render_shift(d, employee, date), 150);
        });
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
                biometric_device:   state.biometric_device || null,
                filter_employee:    state.filter_employee || null,
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
