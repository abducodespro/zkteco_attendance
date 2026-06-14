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

    page.add_inner_button(__("Refresh"), function () {
        load_dashboard();
    });

    // Keep references to chart instances so we can destroy/recreate cleanly
    const chartInstances = {};

    function destroy_charts() {
        Object.keys(chartInstances).forEach((key) => {
            const inst = chartInstances[key];
            if (inst && typeof inst.destroy === "function") {
                try { inst.destroy(); } catch (e) { /* ignore */ }
            }
            delete chartInstances[key];
        });
    }

    function render_charts(charts) {
        if (!charts) return;

        // 1. Check-ins over the last 7 days (line/bar)
        if (charts.checkins_last_7_days && $(wrapper).find("#zkteco-chart-checkins").length) {
            chartInstances.checkins = new frappe.Chart("#zkteco-chart-checkins", {
                title: __("Check-ins (Last 7 Days)"),
                data: {
                    labels: charts.checkins_last_7_days.labels,
                    datasets: [
                        { name: __("Check-ins"), values: charts.checkins_last_7_days.values },
                    ],
                },
                type: "bar",
                height: 220,
                colors: ["#5e64ff"],
                axisOptions: { xIsSeries: 1 },
            });
        }

        // 2. Sync results over the last 7 days (stacked-ish bar via multiple datasets)
        if (charts.sync_results_last_7_days && $(wrapper).find("#zkteco-chart-syncs").length) {
            const s = charts.sync_results_last_7_days;
            chartInstances.syncs = new frappe.Chart("#zkteco-chart-syncs", {
                title: __("Sync Results (Last 7 Days)"),
                data: {
                    labels: s.labels,
                    datasets: [
                        { name: __("New"), values: s.new },
                        { name: __("Duplicate"), values: s.duplicate },
                        { name: __("Failed"), values: s.failed },
                    ],
                },
                type: "bar",
                height: 220,
                colors: ["#28a745", "#ffc107", "#dc3545"],
                axisOptions: { xIsSeries: 1 },
                barOptions: { stacked: 1 },
            });
        }

        // 3. Device status (donut)
        if (charts.device_status && $(wrapper).find("#zkteco-chart-devices").length) {
            chartInstances.devices = new frappe.Chart("#zkteco-chart-devices", {
                title: __("Device Status"),
                data: {
                    labels: charts.device_status.labels,
                    datasets: [{ values: charts.device_status.values }],
                },
                type: "donut",
                height: 220,
                colors: ["#28a745", "#dc3545"],
            });
        }

        // 4. Today's punch breakdown (donut: IN / OUT / Overtime)
        if (charts.todays_punch_breakdown && $(wrapper).find("#zkteco-chart-punches").length) {
            chartInstances.punches = new frappe.Chart("#zkteco-chart-punches", {
                title: __("Today's Check-ins by Type"),
                data: {
                    labels: charts.todays_punch_breakdown.labels,
                    datasets: [{ values: charts.todays_punch_breakdown.values }],
                },
                type: "donut",
                height: 220,
                colors: ["#5e64ff", "#ff5858", "#ffa00a"],
            });
        }
    }

    function load_dashboard() {
        frappe.call({
            method: "zkteco_attendance.zkteco_attendance.page.zkteco_dashboard.zkteco_dashboard.get_data",
            callback(r) {
                if (!r.message) return;
                const d = r.message;

                destroy_charts();
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

                    <div class="row" style="margin-top:24px">
                        <div class="col-sm-6">
                            <div class="zkteco-chart-card">
                                <div id="zkteco-chart-checkins"></div>
                            </div>
                        </div>
                        <div class="col-sm-6">
                            <div class="zkteco-chart-card">
                                <div id="zkteco-chart-syncs"></div>
                            </div>
                        </div>
                    </div>
                    <div class="row" style="margin-top:16px">
                        <div class="col-sm-6">
                            <div class="zkteco-chart-card">
                                <div id="zkteco-chart-devices"></div>
                            </div>
                        </div>
                        <div class="col-sm-6">
                            <div class="zkteco-chart-card">
                                <div id="zkteco-chart-punches"></div>
                            </div>
                        </div>
                    </div>

                    <div style="margin-top:24px">
                        <a class="btn btn-default btn-sm" href="/app/biometric-device">${__("Manage Devices")}</a>
                        &nbsp;
                        <a class="btn btn-default btn-sm" href="/app/attendance-sync-log">${__("View Sync Logs")}</a>
                        &nbsp;
                        <a class="btn btn-default btn-sm" href="/app/attendance-summary">${__("Attendance Summary")}</a>
                    </div>
                </div>`;

                $(wrapper).find(".layout-main-section").append(html);

                // frappe.Chart needs the container to exist in the DOM first
                render_charts(d.charts);
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
