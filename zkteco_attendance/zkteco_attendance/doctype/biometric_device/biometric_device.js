// ZKTeco Attendance — Biometric Device Form
frappe.ui.form.on("Biometric Device", {
    refresh(frm) {

        // ── Test Connection ──────────────────────────────────────
        frm.add_custom_button(__("Test Connection"), function () {
            if (!frm.doc.device_ip) {
                frappe.msgprint(__("Please enter a Device IP first."));
                return;
            }
            frappe.call({
                method: "zkteco_attendance.zkteco_attendance.api.endpoints.test_connection",
                args: { device_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Connecting to device..."),
                callback(r) {
                    if (r.message && r.message.success) {
                        const d = r.message;
                        frappe.msgprint({
                            title: __("Connection Successful"),
                            indicator: "green",
                            message:
                                "<table class='table table-bordered' style='margin-top:8px'>" +
                                "<tr><td><b>Serial Number</b></td><td>" + (d.serial_number || "—") + "</td></tr>" +
                                "<tr><td><b>Firmware</b></td><td>" + (d.firmware_version || "—") + "</td></tr>" +
                                "<tr><td><b>Device Time</b></td><td>" + (d.device_time || "—") + "</td></tr>" +
                                "<tr><td><b>Enrolled Users</b></td><td>" + d.enrolled_users + "</td></tr>" +
                                "<tr><td><b>Attendance Logs</b></td><td>" + d.attendance_logs + "</td></tr>" +
                                "</table>"
                        });
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __("Connection Failed"),
                            indicator: "red",
                            message: (r.message && r.message.error) || __("Unknown error")
                        });
                        frm.reload_doc();
                    }
                }
            });
        }, __("Actions"));

        // ── Pull Checkins ────────────────────────────────────────
        frm.add_custom_button(__("Pull Checkins"), function () {
            frappe.confirm(
                __("Pull attendance logs from this device and create Employee Checkin records?"),
                function () {
                    frappe.call({
                        method: "zkteco_attendance.zkteco_attendance.api.endpoints.sync_device",
                        args: { device_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Queuing sync job..."),
                        callback(r) {
                            if (r.message) {
                                frappe.show_alert({
                                    message: r.message.message || __("Sync job queued."),
                                    indicator: "blue"
                                }, 6);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }, __("Actions"));

        // ── View Sync Logs ───────────────────────────────────────
        frm.add_custom_button(__("View Sync Logs"), function () {
            frappe.set_route("List", "Attendance Sync Log", { device: frm.doc.name });
        }, __("Actions"));

        // ── Status indicator ─────────────────────────────────────
        const colors = { "Active": "green", "Inactive": "red" };
        frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "orange");

        // ── Last sync banner ─────────────────────────────────────
        if (frm.doc.last_sync_time) {
            frm.dashboard.add_comment(
                __("Last sync: ") + frappe.datetime.str_to_user(frm.doc.last_sync_time),
                "blue", true
            );
        } else {
            frm.dashboard.add_comment(__("No sync performed yet."), "orange", true);
        }
    }
});
