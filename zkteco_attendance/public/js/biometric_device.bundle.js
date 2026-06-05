frappe.ui.form.on("Biometric Device", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Test Connection"), () => test_connection(frm), __("Actions"));
        frm.add_custom_button(__("Sync Now"), () => sync_now(frm), __("Actions"));
        frm.add_custom_button(__("View Sync Logs"), () => {
            frappe.set_route("List", "Attendance Sync Log", { device: frm.doc.name });
        }, __("Actions"));
        frm.add_custom_button(__("Employee Mappings"), () => {
            frappe.set_route("List", "Device Employee Mapping", { device: frm.doc.name });
        }, __("Actions"));

        const color = frm.doc.status === "Active" ? "green" : "red";
        frm.page.set_indicator(frm.doc.status, color);

        if (frm.doc.last_sync_time) {
            frm.dashboard.add_comment(
                __("Last Sync: {0}", [frappe.datetime.str_to_user(frm.doc.last_sync_time)]),
                "blue", true
            );
        }
    },

    auto_sync_enabled(frm) {
        frm.toggle_reqd("sync_frequency", frm.doc.auto_sync_enabled);
    },
});

function test_connection(frm) {
    frappe.dom.freeze(__("Testing connection…"));
    frappe.call({
        method: "zkteco_attendance.doctype.biometric_device.biometric_device.test_connection",
        args: { device_name: frm.doc.name },
        always: () => frappe.dom.unfreeze(),
        callback(r) {
            if (r.message && r.message.success) {
                const d = r.message.data;
                frappe.msgprint({
                    title: __("✅ Connection Successful"),
                    indicator: "green",
                    message: `<table class="table table-bordered table-sm">
                        <tr><th>Serial</th><td>${d.device_serial || "—"}</td></tr>
                        <tr><th>Firmware</th><td>${d.firmware_version || "—"}</td></tr>
                        <tr><th>Device Time</th><td>${d.device_time || "—"}</td></tr>
                        <tr><th>Users</th><td>${d.enrolled_users}</td></tr>
                        <tr><th>Records</th><td>${d.attendance_records}</td></tr>
                    </table>`
                });
            } else {
                frappe.msgprint({
                    title: __("❌ Connection Failed"),
                    indicator: "red",
                    message: (r.message && r.message.message) || __("Unknown error")
                });
            }
        }
    });
}

function sync_now(frm) {
    frappe.confirm(
        __("Pull attendance records from <b>{0}</b> now?", [frm.doc.device_name]),
        () => {
            frappe.call({
                method: "zkteco_attendance.doctype.biometric_device.biometric_device.sync_device",
                args: { device_name: frm.doc.name, triggered_by: "Manual" },
                callback(r) {
                    if (r.message && r.message.success) {
                        frappe.show_alert({ message: r.message.message, indicator: "green" }, 6);
                    } else {
                        frappe.msgprint({
                            title: __("Error"),
                            indicator: "red",
                            message: (r.message && r.message.message) || __("Sync failed")
                        });
                    }
                }
            });
        }
    );
}
