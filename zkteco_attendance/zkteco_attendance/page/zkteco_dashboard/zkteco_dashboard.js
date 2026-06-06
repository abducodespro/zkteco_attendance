frappe.pages["zkteco-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("ZKTeco Biometric Dashboard"),
        single_column: true,
    });

    page.add_menu_item(__("Sync All Devices"), function () {
        frappe.call({
            method: "zkteco_attendance.zkteco_attendance.api.endpoints.sync_all_devices",
            freeze: true,
            freeze_message: __("Queuing sync for all devices…"),
            callback(r) {
                if (r.message) {
                    frappe.show_alert({ message: r.message.message, indicator: "blue" }, 6);
                    load_dashboard();
                }
            },
        });
    });

    function load_dashboard() {
        frappe.call({
            method: "zkteco_attendance.zkteco_attendance.page.zkteco_dashboard.zkteco_dashboard.get_data",
            callback(r) {
                if (!r.message) return;
                const d = r.message;

                $(wrapper).find(".zkteco-dashboard").remove();

                const html = `
                <div class="zkteco-dashboard" style="padding:24px">
                    <div class="row">
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card">
                                <div class="stat-value">${d.total_devices}</div>
                                <div class="stat-label">${__("Total Devices")}</div>
                            </div>
                        </div>
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card online">
                                <div class="stat-value">${d.online_devices}</div>
                                <div class="stat-label">${__("Online Devices")}</div>
                            </div>
                        </div>
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card offline">
                                <div class="stat-value">${d.offline_devices}</div>
                                <div class="stat-label">${__("Offline Devices")}</div>
                            </div>
                        </div>
                    </div>
                    <div class="row" style="margin-top:16px">
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card">
                                <div class="stat-value">${d.todays_checkins}</div>
                                <div class="stat-label">${__("Today's Check-ins")}</div>
                            </div>
                        </div>
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card failed">
                                <div class="stat-value">${d.failed_syncs_today}</div>
                                <div class="stat-label">${__("Failed Syncs Today")}</div>
                            </div>
                        </div>
                        <div class="col-sm-4">
                            <div class="zkteco-stat-card">
                                <div class="stat-value" style="font-size:1rem">
                                    ${d.last_sync ? frappe.datetime.str_to_user(d.last_sync.start_time) : __("Never")}
                                </div>
                                <div class="stat-label">${__("Last Sync")}</div>
                            </div>
                        </div>
                    </div>
                    <div style="margin-top:24px">
                        <a class="btn btn-default btn-sm" href="/app/biometric-device">${__("Manage Devices")}</a>
                        &nbsp;
                        <a class="btn btn-default btn-sm" href="/app/attendance-sync-log">${__("View Sync Logs")}</a>
                    </div>
                </div>`;

                $(wrapper).find(".layout-main-section").append(html);
            },
        });
    }

    load_dashboard();

    // Auto-refresh every 60s
    frappe.pages["zkteco-dashboard"].refresh_interval = setInterval(load_dashboard, 60000);
};

frappe.pages["zkteco-dashboard"].on_page_show = function () {
    // handled above
};
