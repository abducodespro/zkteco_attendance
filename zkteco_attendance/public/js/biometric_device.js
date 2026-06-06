// ZKTeco Attendance — Biometric Device Form JS

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

        // ── Pull Checkins ────────────────────────────────────────────────
        frm.add_custom_button(__("Pull Checkins"), function () {
            frappe.confirm(
                __("This will pull attendance logs from <b>{0}</b> and create Employee Checkin records. Continue?",
                    [frm.doc.device_name]),
                function () {
                    frm.call({
                        method: "zkteco_attendance.zkteco_attendance.api.endpoints.sync_device",
                        args: { device_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Queuing sync job…"),
                        callback(r) {
                            if (r.message) {
                                frappe.show_alert({
                                    message: r.message.message || __("Sync job queued."),
                                    indicator: "blue",
                                }, 6);
                                frm.reload_doc();
                            }
                        },
                    });
                }
            );
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
});
