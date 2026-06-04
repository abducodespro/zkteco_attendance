/**
 * Biometric Device — Form-level JavaScript
 * Adds action buttons: Test Connection, Sync Now, View Logs
 */
frappe.ui.form.on("Biometric Device", {
	refresh(frm) {
		frm.disable_save();

		// ── Action Buttons ──────────────────────────────────

		if (!frm.is_new()) {
			frm.add_custom_button(__("Test Connection"), () => test_connection(frm), __("Actions"));
			frm.add_custom_button(__("Sync Now"), () => sync_now(frm), __("Actions"));
			frm.add_custom_button(__("View Sync Logs"), () => view_logs(frm), __("Actions"));
			frm.add_custom_button(__("Manage Employee Mappings"), () => manage_mappings(frm), __("Actions"));
			frm.add_custom_button(__("Open Dashboard"), () => frappe.set_route("zkteco-dashboard"), __("Actions"));
		}

		frm.enable_save();

		// ── Status Indicator ────────────────────────────────
		render_status_badge(frm);

		// ── Last Sync ───────────────────────────────────────
		if (frm.doc.last_sync_time) {
			frm.dashboard.add_comment(
				__("Last Sync: {0}", [frappe.datetime.str_to_user(frm.doc.last_sync_time)]),
				"blue",
				true
			);
		}
	},

	auto_sync_enabled(frm) {
		frm.toggle_reqd("sync_frequency", frm.doc.auto_sync_enabled);
	},
});

// ─── Helpers ───────────────────────────────────────────────────

function render_status_badge(frm) {
	const color = frm.doc.status === "Active" ? "green" : "red";
	frm.page.set_indicator(frm.doc.status, color);
}

function test_connection(frm) {
	if (!frm.doc.device_ip) {
		frappe.msgprint(__("Please enter the Device IP first."));
		return;
	}

	frappe.dom.freeze(__("Testing connection to {0}…", [frm.doc.device_name]));

	frappe.call({
		method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.test_connection",
		args: { device_name: frm.doc.name },
		always: () => frappe.dom.unfreeze(),
		callback: (r) => {
			if (r.message?.success) {
				const info = r.message.data;
				frappe.msgprint({
					title: __("✅ Connection Successful"),
					indicator: "green",
					message: `
            <table class="table table-bordered table-sm">
              <tr><th>${__("IP / Port")}</th><td>${info.device_ip}:${info.port}</td></tr>
              <tr><th>${__("Serial Number")}</th><td>${info.device_serial || "—"}</td></tr>
              <tr><th>${__("Firmware Version")}</th><td>${info.firmware_version || "—"}</td></tr>
              <tr><th>${__("Device Time")}</th><td>${info.device_time || "—"}</td></tr>
              <tr><th>${__("Enrolled Users")}</th><td>${info.enrolled_users}</td></tr>
              <tr><th>${__("Attendance Records")}</th><td>${info.attendance_records}</td></tr>
            </table>`,
				});
			} else {
				frappe.msgprint({
					title: __("❌ Connection Failed"),
					indicator: "red",
					message: r.message?.message || __("Unknown error"),
				});
			}
		},
	});
}

function sync_now(frm) {
	frappe.confirm(
		__("Pull attendance records from <b>{0}</b> now?<br><br>This will run as a background job.", [
			frm.doc.device_name,
		]),
		() => {
			frappe.call({
				method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.sync_device",
				args: {
					device_name: frm.doc.name,
					triggered_by: "Manual",
				},
				callback: (r) => {
					if (r.message?.success) {
						frappe.show_alert({ message: r.message.message, indicator: "green" }, 6);
					} else {
						frappe.msgprint({
							title: __("Sync Failed"),
							indicator: "red",
							message: r.message?.message || __("Could not start sync"),
						});
					}
				},
			});
		}
	);
}

function view_logs(frm) {
	frappe.set_route("List", "Attendance Sync Log", { device: frm.doc.name });
}

function manage_mappings(frm) {
	frappe.set_route("List", "Device Employee Mapping", { device: frm.doc.name });
}
