/**
 * ZKTeco Attendance Dashboard
 * Frappe Page: zkteco-dashboard
 */
frappe.pages["zkteco-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("ZKTeco Attendance Dashboard"),
		single_column: false,
	});

	// Add toolbar buttons
	page.add_primary_action(__("Sync All Devices"), () => sync_all_devices(), "octicon octicon-sync");
	page.add_action_item(__("Refresh Dashboard"), () => load_dashboard());

	// Render layout
	$(wrapper).find(".page-content").html(`
    <div id="zk-dashboard">
      <div class="zk-stat-row row" id="zk-stat-cards">
        ${stat_card("zk-total", "Total Devices", "&#128276;", "#6c757d")}
        ${stat_card("zk-active", "Active Devices", "&#9989;", "#28a745")}
        ${stat_card("zk-inactive", "Inactive Devices", "&#10060;", "#dc3545")}
        ${stat_card("zk-checkins", "Today's Checkins", "&#128100;", "#007bff")}
        ${stat_card("zk-failed", "Failed Syncs (24h)", "&#9888;", "#ffc107")}
      </div>

      <div class="row mt-4">
        <div class="col-md-8">
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <h5 class="mb-0">${__("Device Status")}</h5>
              <button class="btn btn-sm btn-light" onclick="frappe.set_route('List','Biometric Device')">
                ${__("View All")}
              </button>
            </div>
            <div class="card-body p-0">
              <div id="zk-device-table">
                <div class="zk-loading">${__("Loading...")}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-md-4">
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <h5 class="mb-0">${__("Recent Sync Logs")}</h5>
              <button class="btn btn-sm btn-light" onclick="frappe.set_route('List','Attendance Sync Log')">
                ${__("View All")}
              </button>
            </div>
            <div class="card-body p-0">
              <div id="zk-sync-logs">
                <div class="zk-loading">${__("Loading...")}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <style>
      #zk-dashboard .zk-stat-row { margin: 0 -8px; }
      .zk-stat-card {
        border-radius: 10px;
        padding: 20px 24px;
        margin: 8px;
        color: #fff;
        flex: 1 1 0;
        min-width: 140px;
        display: flex;
        flex-direction: column;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      }
      .zk-stat-card .stat-label { font-size: 12px; opacity: 0.88; text-transform: uppercase; letter-spacing: 0.5px; }
      .zk-stat-card .stat-value { font-size: 36px; font-weight: 700; margin: 4px 0; }
      .zk-stat-card .stat-icon { font-size: 22px; }
      #zk-device-table table { width: 100%; font-size: 13px; }
      #zk-device-table th { background: var(--bg-light-gray); padding: 10px 16px; font-weight: 600; }
      #zk-device-table td { padding: 10px 16px; border-top: 1px solid var(--border-color); }
      .badge-success { background: #28a745; color: #fff; }
      .badge-danger { background: #dc3545; color: #fff; }
      .badge-warning { background: #ffc107; color: #212529; }
      .badge-secondary { background: #6c757d; color: #fff; }
      .zk-loading { padding: 30px; text-align: center; color: var(--text-muted); }
    </style>
  `);

	load_dashboard();

	// Auto-refresh every 60 seconds
	setInterval(load_dashboard, 60000);

	// ─── Helpers ───────────────────────────────────

	function stat_card(id, label, icon, bg) {
		return `
      <div class="col">
        <div class="zk-stat-card" style="background:${bg}" id="${id}">
          <div class="stat-icon">${icon}</div>
          <div class="stat-value">—</div>
          <div class="stat-label">${__(label)}</div>
        </div>
      </div>`;
	}

	function load_dashboard() {
		frappe.call({
			method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.get_dashboard_stats",
			callback: (r) => {
				if (r.exc) return;
				const d = r.message;

				$("#zk-total .stat-value").text(d.total_devices);
				$("#zk-active .stat-value").text(d.active_devices);
				$("#zk-inactive .stat-value").text(d.inactive_devices);
				$("#zk-checkins .stat-value").text(d.today_checkins);
				$("#zk-failed .stat-value").text(d.failed_syncs_24h);

				load_device_table();
				load_sync_logs();
			},
		});
	}

	function load_device_table() {
		frappe.db.get_list("Biometric Device", {
			fields: ["name", "device_ip", "port", "status", "last_sync_time", "location", "company"],
			limit: 20,
			order_by: "status asc, name asc",
		}).then((devices) => {
			if (!devices || !devices.length) {
				$("#zk-device-table").html(`<div class="zk-loading">${__("No devices configured")}</div>`);
				return;
			}

			let rows = devices.map((d) => {
				const badge = d.status === "Active"
					? `<span class="badge badge-success">Active</span>`
					: `<span class="badge badge-secondary">Inactive</span>`;
				const lastSync = d.last_sync_time
					? frappe.datetime.str_to_user(d.last_sync_time)
					: `<span class="text-muted">Never</span>`;

				return `<tr>
          <td><a href="/app/biometric-device/${d.name}">${d.name}</a></td>
          <td>${d.device_ip}:${d.port}</td>
          <td>${d.location || "—"}</td>
          <td>${badge}</td>
          <td>${lastSync}</td>
          <td>
            <button class="btn btn-xs btn-default" onclick="test_device('${d.name}')">
              ${__("Test")}
            </button>
            <button class="btn btn-xs btn-primary" onclick="sync_device('${d.name}')">
              ${__("Sync")}
            </button>
          </td>
        </tr>`;
			});

			$("#zk-device-table").html(`
        <table>
          <thead>
            <tr>
              <th>${__("Device")}</th>
              <th>${__("IP:Port")}</th>
              <th>${__("Location")}</th>
              <th>${__("Status")}</th>
              <th>${__("Last Sync")}</th>
              <th>${__("Actions")}</th>
            </tr>
          </thead>
          <tbody>${rows.join("")}</tbody>
        </table>`);
		});
	}

	function load_sync_logs() {
		frappe.call({
			method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.get_sync_logs",
			args: { limit: 15 },
			callback: (r) => {
				if (!r.message || !r.message.length) {
					$("#zk-sync-logs").html(`<div class="zk-loading">${__("No sync logs yet")}</div>`);
					return;
				}

				const rows = r.message.map((log) => {
					const badge = {
						Success: "badge-success",
						Failed: "badge-danger",
						Partial: "badge-warning",
						"In Progress": "badge-secondary",
					}[log.sync_status] || "badge-secondary";

					return `<div style="padding:10px 16px; border-bottom:1px solid var(--border-color)">
            <div class="d-flex justify-content-between">
              <strong><a href="/app/attendance-sync-log/${log.name}">${log.device}</a></strong>
              <span class="badge ${badge}">${log.sync_status}</span>
            </div>
            <div class="text-muted" style="font-size:12px; margin-top:2px">
              ${frappe.datetime.str_to_user(log.start_time)} &bull;
              ${__("Created")}: <b>${log.new_records_created || 0}</b> &bull;
              ${__("Failed")}: <b>${log.failed_records || 0}</b>
            </div>
          </div>`;
				});

				$("#zk-sync-logs").html(rows.join(""));
			},
		});
	}

	// Expose to global scope for inline onclick handlers
	window.sync_device = function (device_name) {
		frappe.confirm(
			__("Sync device <b>{0}</b> now?", [device_name]),
			() => {
				frappe.call({
					method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.sync_device",
					args: { device_name, triggered_by: "Manual" },
					callback: (r) => {
						frappe.show_alert({ message: r.message?.message || __("Sync job queued"), indicator: "green" });
						setTimeout(load_dashboard, 3000);
					},
				});
			}
		);
	};

	window.test_device = function (device_name) {
		const d = frappe.msgprint(__("Testing connection to {0}…", [device_name]));
		frappe.call({
			method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.test_connection",
			args: { device_name },
			callback: (r) => {
				frappe.hide_msgprint();
				if (r.message?.success) {
					const info = r.message.data;
					frappe.msgprint({
						title: __("Connection Successful — {0}", [device_name]),
						indicator: "green",
						message: `
              <table class="table table-bordered table-sm">
                <tr><th>${__("Serial")}</th><td>${info.device_serial || "—"}</td></tr>
                <tr><th>${__("Firmware")}</th><td>${info.firmware_version || "—"}</td></tr>
                <tr><th>${__("Device Time")}</th><td>${info.device_time || "—"}</td></tr>
                <tr><th>${__("Users")}</th><td>${info.enrolled_users}</td></tr>
                <tr><th>${__("Records")}</th><td>${info.attendance_records}</td></tr>
              </table>`,
					});
				} else {
					frappe.msgprint({
						title: __("Connection Failed"),
						indicator: "red",
						message: r.message?.message || __("Unknown error"),
					});
				}
			},
		});
	};

	function sync_all_devices() {
		frappe.confirm(
			__("Sync ALL active devices now?"),
			() => {
				frappe.call({
					method: "zkteco_attendance.zkteco_attendance.doctype.biometric_device.biometric_device.sync_all_devices",
					callback: (r) => {
						frappe.show_alert({ message: r.message?.message, indicator: "green" });
						setTimeout(load_dashboard, 3000);
					},
				});
			}
		);
	}
};
