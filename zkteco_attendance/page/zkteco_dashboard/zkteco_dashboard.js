frappe.pages["zkteco-dashboard"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("ZKTeco Attendance Dashboard"),
        single_column: false,
    });

    page.add_primary_action(__("Sync All Devices"), () => {
        frappe.confirm(__("Sync ALL active devices now?"), () => {
            frappe.call({
                method: "zkteco_attendance.doctype.biometric_device.biometric_device.sync_all_devices",
                callback(r) {
                    frappe.show_alert({ message: r.message && r.message.message, indicator: "green" });
                    setTimeout(load_dashboard, 3000);
                }
            });
        });
    }, "octicon octicon-sync");

    page.add_action_item(__("Refresh"), () => load_dashboard());

    $(wrapper).find(".page-content").html(`
        <div id="zk-dashboard" style="padding:20px">
            <div class="row" id="zk-stat-cards" style="margin-bottom:20px"></div>
            <div class="row">
                <div class="col-md-8">
                    <div class="card">
                        <div class="card-header"><h5 style="margin:0">${__("Devices")}</h5></div>
                        <div id="zk-device-table"><div style="padding:30px;text-align:center">${__("Loading…")}</div></div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header"><h5 style="margin:0">${__("Recent Syncs")}</h5></div>
                        <div id="zk-sync-logs"><div style="padding:30px;text-align:center">${__("Loading…")}</div></div>
                    </div>
                </div>
            </div>
        </div>
        <style>
            .zk-stat { border-radius:10px; padding:20px; color:#fff; text-align:center; margin:5px; }
            .zk-stat .val { font-size:36px; font-weight:700; }
            .zk-stat .lbl { font-size:12px; opacity:.88; text-transform:uppercase; }
        </style>
    `);

    load_dashboard();
    setInterval(load_dashboard, 60000);

    function load_dashboard() {
        frappe.call({
            method: "zkteco_attendance.doctype.biometric_device.biometric_device.get_dashboard_stats",
            callback(r) {
                if (!r.message) return;
                const d = r.message;
                $("#zk-stat-cards").html(`
                    <div class="col"><div class="zk-stat" style="background:#6c757d">
                        <div class="val">${d.total_devices}</div><div class="lbl">${__("Total Devices")}</div></div></div>
                    <div class="col"><div class="zk-stat" style="background:#28a745">
                        <div class="val">${d.active_devices}</div><div class="lbl">${__("Active")}</div></div></div>
                    <div class="col"><div class="zk-stat" style="background:#dc3545">
                        <div class="val">${d.inactive_devices}</div><div class="lbl">${__("Inactive")}</div></div></div>
                    <div class="col"><div class="zk-stat" style="background:#007bff">
                        <div class="val">${d.today_checkins}</div><div class="lbl">${__("Today Checkins")}</div></div></div>
                    <div class="col"><div class="zk-stat" style="background:#ffc107;color:#333">
                        <div class="val">${d.failed_syncs_24h}</div><div class="lbl">${__("Failed Syncs 24h")}</div></div></div>
                `);
                load_device_table();
                load_sync_logs();
            }
        });
    }

    function load_device_table() {
        frappe.db.get_list("Biometric Device", {
            fields: ["name","device_ip","port","status","last_sync_time","location"],
            limit: 20, order_by: "name asc"
        }).then(devices => {
            if (!devices.length) {
                $("#zk-device-table").html(`<div style="padding:30px;text-align:center">${__("No devices")}</div>`);
                return;
            }
            const rows = devices.map(d => {
                const badge = d.status === "Active"
                    ? `<span class="badge badge-success">Active</span>`
                    : `<span class="badge badge-secondary">Inactive</span>`;
                const sync = d.last_sync_time ? frappe.datetime.str_to_user(d.last_sync_time) : "Never";
                return `<tr>
                    <td><a href="/app/biometric-device/${d.name}">${d.name}</a></td>
                    <td>${d.device_ip}:${d.port}</td>
                    <td>${d.location || "—"}</td>
                    <td>${badge}</td>
                    <td>${sync}</td>
                    <td>
                        <button class="btn btn-xs btn-default" onclick="window._zk_test('${d.name}')">${__("Test")}</button>
                        <button class="btn btn-xs btn-primary" onclick="window._zk_sync('${d.name}')">${__("Sync")}</button>
                    </td>
                </tr>`;
            });
            $("#zk-device-table").html(`<table class="table table-sm" style="margin:0">
                <thead><tr><th>${__("Device")}</th><th>${__("IP:Port")}</th><th>${__("Location")}</th>
                <th>${__("Status")}</th><th>${__("Last Sync")}</th><th></th></tr></thead>
                <tbody>${rows.join("")}</tbody></table>`);
        });
    }

    function load_sync_logs() {
        frappe.call({
            method: "zkteco_attendance.doctype.biometric_device.biometric_device.get_sync_logs",
            args: { limit: 10 },
            callback(r) {
                if (!r.message || !r.message.length) {
                    $("#zk-sync-logs").html(`<div style="padding:30px;text-align:center">${__("No logs")}</div>`);
                    return;
                }
                const colors = {Success:"success",Failed:"danger",Partial:"warning","In Progress":"secondary"};
                const rows = r.message.map(log => `
                    <div style="padding:10px 16px;border-bottom:1px solid var(--border-color)">
                        <div class="d-flex justify-content-between">
                            <strong><a href="/app/attendance-sync-log/${log.name}">${log.device}</a></strong>
                            <span class="badge badge-${colors[log.sync_status]||"secondary"}">${log.sync_status}</span>
                        </div>
                        <div class="text-muted" style="font-size:12px">
                            ${frappe.datetime.str_to_user(log.start_time)} &bull;
                            Created: <b>${log.new_records_created||0}</b> &bull;
                            Failed: <b>${log.failed_records||0}</b>
                        </div>
                    </div>`);
                $("#zk-sync-logs").html(rows.join(""));
            }
        });
    }

    window._zk_sync = function(name) {
        frappe.confirm(__("Sync <b>{0}</b> now?", [name]), () => {
            frappe.call({
                method: "zkteco_attendance.doctype.biometric_device.biometric_device.sync_device",
                args: { device_name: name, triggered_by: "Manual" },
                callback(r) {
                    frappe.show_alert({ message: r.message && r.message.message, indicator: "green" });
                    setTimeout(load_dashboard, 3000);
                }
            });
        });
    };

    window._zk_test = function(name) {
        frappe.dom.freeze(__("Testing…"));
        frappe.call({
            method: "zkteco_attendance.doctype.biometric_device.biometric_device.test_connection",
            args: { device_name: name },
            always: () => frappe.dom.unfreeze(),
            callback(r) {
                if (r.message && r.message.success) {
                    const d = r.message.data;
                    frappe.msgprint({
                        title: __("Connected: {0}", [name]), indicator: "green",
                        message: `Serial: ${d.device_serial}<br>Firmware: ${d.firmware_version}<br>
                            Time: ${d.device_time}<br>Users: ${d.enrolled_users}<br>Records: ${d.attendance_records}`
                    });
                } else {
                    frappe.msgprint({ title: __("Failed"), indicator: "red",
                        message: r.message && r.message.message });
                }
            }
        });
    };
};
