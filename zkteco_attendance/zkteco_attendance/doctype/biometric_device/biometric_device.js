// ZKTeco Attendance — Biometric Device Form JS
// Compatible with Frappe v14 / v15 / v16

frappe.ui.form.on("Biometric Device", {
    refresh(frm) {
        frm.disable_save();  // re-enable
        frm.enable_save();

        // ── Test Connection ──────────────────────────────────────────────
        frm.add_custom_button(__("Test Connection"), function () {
            if (!frm.doc.device_ip) {
                frappe.msgprint(__("Please enter a Device IP first."));
                return;
            }
            frm.call({
                method: "zkteco_attendance.zkteco_attendance.api.endpoints.test_connection",
                args: { device_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Connecting to device…"),
                callback(r) {
                    if (r.message && r.message.success) {
                        const d = r.message;
                        frappe.msgprint({
                            title: __("Connection Successful ✓"),
                            indicator: "green",
                            message: `
                                <table class="table table-bordered" style="margin-top:8px">
                                    <tr><td><b>${__("Serial Number")}</b></td><td>${d.serial_number || "—"}</td></tr>
                                    <tr><td><b>${__("Firmware")}</b></td><td>${d.firmware_version || "—"}</td></tr>
                                    <tr><td><b>${__("Device Time")}</b></td><td>${d.device_time || "—"}</td></tr>
                                    <tr><td><b>${__("Enrolled Users")}</b></td><td>${d.enrolled_users}</td></tr>
                                    <tr><td><b>${__("Attendance Logs")}</b></td><td>${d.attendance_logs}</td></tr>
                                </table>`,
                        });
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __("Connection Failed"),
                            indicator: "red",
                            message: (r.message && r.message.error) || __("Unknown error"),
                        });
                        frm.reload_doc();
                    }
                },
            });
        }, __("Actions"));

        // ── Pull Checkins (with live progress + results) ──────────────────
        frm.add_custom_button(__("Pull Checkins"), function () {
            frm.trigger("pull_checkins_with_progress");
        }, __("Actions"));

        // ── View Sync Logs ───────────────────────────────────────────────
        frm.add_custom_button(__("View Sync Logs"), function () {
            frappe.set_route("List", "Attendance Sync Log", { device: frm.doc.name });
        }, __("Actions"));

        // ── Status badge ────────────────────────────────────────────────
        const statusColor = { "Active": "green", "Inactive": "red" };
        frm.page.set_indicator(
            frm.doc.status,
            statusColor[frm.doc.status] || "orange"
        );

        // ── Last sync info ───────────────────────────────────────────────
        if (frm.doc.last_sync_time) {
            frm.dashboard.add_comment(
                __("Last successful sync: <b>{0}</b>",
                    [frappe.datetime.str_to_user(frm.doc.last_sync_time)]),
                "blue",
                true
            );
        } else {
            frm.dashboard.add_comment(__("No sync has been performed yet."), "orange", true);
        }
    },

    pull_checkins_with_progress(frm) {
        if (frm.doc.status !== "Active") {
            frappe.msgprint({
                title: __("Device Not Active"),
                indicator: "red",
                message: __("This device is not Active. Please run Test Connection first."),
            });
            return;
        }

        frappe.confirm(
            __("This will connect to <b>{0}</b> now, pull attendance logs, and create Employee Checkin records. This may take a little while for devices with many logs. Continue?",
                [frm.doc.device_name]),
            function () {
                frm.trigger("_run_pull_checkins");
            }
        );
    },

    _run_pull_checkins(frm) {
        // ── Build a progress dialog ────────────────────────────────────────
        const dialog = new frappe.ui.Dialog({
            title: __("Pulling Check-ins from {0}", [frm.doc.device_name]),
            size: "large",
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "progress_html",
                },
            ],
        });

        const $body = dialog.fields_dict.progress_html.$wrapper;
        $body.html(`
            <div class="zkteco-pull-progress">
                <div class="zkteco-pull-stage text-muted" style="margin-bottom:8px;">
                    ${__("Starting…")}
                </div>
                <div class="progress" style="height:18px;">
                    <div class="progress-bar progress-bar-striped active zkteco-pull-bar"
                         role="progressbar" style="width:5%;">
                    </div>
                </div>
                <div class="zkteco-pull-counts" style="margin-top:14px; display:none;">
                    <table class="table table-bordered table-sm" style="margin-bottom:0;">
                        <tr>
                            <td>${__("Total Pulled")}</td><td class="text-right zkteco-cnt-total">0</td>
                            <td>${__("New")}</td><td class="text-right text-success zkteco-cnt-new">0</td>
                        </tr>
                        <tr>
                            <td>${__("Duplicates")}</td><td class="text-right zkteco-cnt-dupes">0</td>
                            <td>${__("Failed")}</td><td class="text-right text-danger zkteco-cnt-failed">0</td>
                        </tr>
                        <tr>
                            <td>${__("Overtime Punches")}</td><td class="text-right text-warning zkteco-cnt-ot">0</td>
                            <td>${__("Status")}</td><td class="text-right zkteco-cnt-status">—</td>
                        </tr>
                    </table>
                </div>
                <div class="zkteco-pull-errors text-danger" style="margin-top:10px; display:none; max-height:150px; overflow:auto; font-size:12px;"></div>
            </div>
        `);

        dialog.show();
        dialog.get_close_btn().hide();

        const $stage  = $body.find(".zkteco-pull-stage");
        const $bar    = $body.find(".zkteco-pull-bar");
        const $counts = $body.find(".zkteco-pull-counts");
        const $errors = $body.find(".zkteco-pull-errors");

        const setProgress = (pct, text) => {
            pct = Math.max(0, Math.min(100, pct));
            $bar.css("width", pct + "%");
            if (text) $stage.text(text);
        };

        // ── Subscribe to realtime progress events ─────────────────────────
        const handler = (data) => {
            if (!data || data.device !== frm.doc.name) return;

            switch (data.stage) {
                case "connecting":
                    setProgress(5, data.message);
                    break;
                case "fetching":
                    setProgress(10, data.message);
                    break;
                case "fetched":
                    setProgress(15, data.message);
                    break;
                case "processing_raw": {
                    const pct = data.total ? 15 + (data.current / data.total) * 35 : 15;
                    setProgress(pct, data.message);
                    break;
                }
                case "filtered":
                    setProgress(55, data.message);
                    break;
                case "creating_checkins": {
                    const pct = data.total ? 55 + (data.current / data.total) * 40 : 55;
                    setProgress(pct, data.message);
                    $counts.show();
                    $body.find(".zkteco-cnt-new").text(data.new_records ?? 0);
                    $body.find(".zkteco-cnt-dupes").text(data.duplicates ?? 0);
                    $body.find(".zkteco-cnt-failed").text(data.failed ?? 0);
                    $body.find(".zkteco-cnt-ot").text(data.overtime_records ?? 0);
                    $body.find(".zkteco-cnt-total").text(data.total ?? 0);
                    break;
                }
                case "done":
                    setProgress(100, data.message || __("Done."));
                    break;
                case "error":
                case "failed":
                    setProgress(100, data.message || __("Failed."));
                    $stage.removeClass("text-muted").addClass("text-danger");
                    break;
            }
        };

        frappe.realtime.on("zkteco_pull_progress", handler);

        // ── Run the synchronous pull ───────────────────────────────────────
        // Note: for devices with very large numbers of stored logs, ensure
        // your web server / gunicorn worker timeout (and any reverse proxy
        // timeout) is generous enough (e.g. 5-10 minutes), since this runs
        // as a single foreground request while progress is streamed via
        // realtime events.
        frm.call({
            method: "zkteco_attendance.zkteco_attendance.api.endpoints.pull_checkins_now",
            args: { device_name: frm.doc.name },
            callback(r) {
                frappe.realtime.off("zkteco_pull_progress", handler);

                if (!r.message) {
                    setProgress(100, __("No response from server."));
                    dialog.get_close_btn().show();
                    return;
                }

                const res = r.message;

                if (!res.success) {
                    setProgress(100, __("Pull failed."));
                    $stage.removeClass("text-muted").addClass("text-danger");
                    $errors.show().text(res.error || __("Unknown error"));
                    dialog.get_close_btn().show();
                    frm.reload_doc();
                    return;
                }

                setProgress(100, __("Pull completed."));
                $counts.show();
                $body.find(".zkteco-cnt-total").text(res.total_records ?? 0);
                $body.find(".zkteco-cnt-new").text(res.new_records ?? 0);
                $body.find(".zkteco-cnt-dupes").text(res.duplicates ?? 0);
                $body.find(".zkteco-cnt-failed").text(res.failed ?? 0);
                $body.find(".zkteco-cnt-ot").text(res.overtime_records ?? 0);

                const statusColors = { Success: "text-success", Partial: "text-warning", Failed: "text-danger" };
                $body.find(".zkteco-cnt-status")
                    .removeClass("text-success text-warning text-danger")
                    .addClass(statusColors[res.sync_status] || "")
                    .text(res.sync_status || "—");

                if (res.errors && res.errors.length) {
                    $errors.show().html(
                        "<b>" + __("Issues") + ":</b><br>" +
                        res.errors.map(e => frappe.utils.escape_html(e)).join("<br>")
                    );
                }

                frappe.show_alert({
                    message: __("Pulled {0} record(s): {1} new, {2} duplicate(s), {3} failed.",
                        [res.total_records, res.new_records, res.duplicates, res.failed]),
                    indicator: res.sync_status === "Success" ? "green" : (res.sync_status === "Partial" ? "orange" : "red"),
                }, 8);

                dialog.get_close_btn().show();
                frm.reload_doc();
            },
            error() {
                frappe.realtime.off("zkteco_pull_progress", handler);
                setProgress(100, __("Pull failed."));
                $stage.removeClass("text-muted").addClass("text-danger");
                dialog.get_close_btn().show();
            },
        });
    },
});
