const root = document.querySelector("[data-page]");

if (root) {
    const page = root.dataset.page;
    const apiUrl = root.dataset.apiUrl;
    const wsUrl = root.dataset.wsUrl;
    let websocket = null;

    const state = {
        dashboard: null,
        devices: [],
        alerts: [],
        settings: null,
        simulator: null,
    };

    const helpers = {
        formatNumber(value, digits = 2) {
            if (value === undefined || value === null || Number.isNaN(value)) return "-";
            return Number(value).toFixed(digits);
        },
        formatDate(value) {
            if (!value) return "-";
            return new Date(value).toLocaleString("zh-CN", { hour12: false });
        },
        statusPill(status) {
            const css = status === "online" ? "online" : "offline";
            const text = status === "online" ? "在线" : "离线";
            return `<span class="status-pill ${css}">${text}</span>`;
        },
        flagText(predictedLabel) {
            return predictedLabel === 1
                ? `<span class="flag-danger">异常</span>`
                : `<span class="flag-normal">正常</span>`;
        },
        escape(value) {
            return String(value ?? "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;");
        },
    };

    async function loadJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.message || `Request failed: ${response.status}`);
        }
        return response.json();
    }

    async function bootstrap() {
        const bootstrapMap = {
            dashboard: () => loadJson("/api/dashboard").then((data) => applyEvent("dashboard", data)),
            devices: () => loadJson("/api/devices").then((data) => applyEvent("devices", data)),
            alerts: () => loadJson("/api/alerts").then((data) => applyEvent("alerts", data)),
            history: renderHistory,
            settings: async () => {
                applyEvent("settings", await loadJson("/api/settings"));
                state.simulator = await loadJson("/api/simulator");
                renderSimulatorStatus();
            },
        };
        if (bootstrapMap[page]) await bootstrapMap[page]();
    }

    function connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        websocket = new WebSocket(`${protocol}://${window.location.host}${wsUrl}`);
        websocket.addEventListener("open", () => websocket.send("bootstrap"));
        websocket.addEventListener("message", (event) => {
            const message = JSON.parse(event.data);
            if (message.event === "bootstrap") {
                Object.entries(message.data).forEach(([eventName, data]) => applyEvent(eventName, data));
                return;
            }
            applyEvent(message.event, message.data);
        });
        websocket.addEventListener("close", () => setTimeout(connectWebSocket, 2000));
    }

    function applyEvent(eventName, data) {
        if (eventName === "dashboard") {
            state.dashboard = data;
            if (page === "dashboard") renderDashboard();
            if (data) {
                state.devices = data.devices || state.devices;
                state.alerts = data.alerts || state.alerts;
            }
        }
        if (eventName === "devices") {
            state.devices = data || [];
            if (page === "devices") renderDevices();
        }
        if (eventName === "alerts") {
            state.alerts = data || [];
            if (page === "alerts") renderAlerts();
            if (page === "dashboard" && state.dashboard) {
                state.dashboard.alerts = state.alerts;
                renderDashboard();
            }
        }
        if (eventName === "settings") {
            state.settings = data;
            if (page === "settings") renderSettings();
        }
    }

    function renderDashboard() {
        const data = state.dashboard;
        if (!data) return;
        document.getElementById("totalDevices").textContent = data.summary.total_devices;
        document.getElementById("onlineDevices").textContent = data.summary.online_devices;
        document.getElementById("totalReadings").textContent = data.summary.total_readings;
        document.getElementById("anomalies24h").textContent = data.summary.anomalies_24h;

        document.getElementById("deviceRows").innerHTML = data.devices.map((device) => {
            const latest = device.latest_reading || {};
            return `
                <tr>
                    <td>${helpers.escape(device.meter_id)}<br><small>${helpers.escape(device.name)}</small></td>
                    <td>${helpers.escape(device.location)}</td>
                    <td>${helpers.statusPill(device.status)}</td>
                    <td>${helpers.formatNumber(latest.instant_flow, 4)}<br><small>${helpers.flagText(latest.predicted_label)}</small></td>
                    <td>${helpers.formatNumber(latest.cumulative_usage, 2)}</td>
                    <td>${helpers.formatNumber(latest.battery_voltage, 2)} V</td>
                    <td>${helpers.formatNumber(latest.signal_strength, 1)}</td>
                    <td>${helpers.formatDate(device.last_seen_at)}</td>
                </tr>
            `;
        }).join("");

        document.getElementById("alertList").innerHTML = data.alerts.length
            ? data.alerts.map(renderAlertCard).join("")
            : `<div class="empty-state">最近没有新的异常告警。</div>`;

        drawChart(data.chart || []);
    }

    function renderDevices() {
        const body = document.getElementById("devicesTableBody");
        if (!body) return;
        body.innerHTML = state.devices.map((device) => `
            <tr>
                <td>${helpers.escape(device.meter_id)}</td>
                <td>${helpers.escape(device.name)}</td>
                <td>${helpers.escape(device.location)}</td>
                <td>${helpers.statusPill(device.status)}</td>
                <td>${device.anomaly_count}</td>
                <td><code>${helpers.escape(device.api_key)}</code></td>
                <td>${helpers.formatDate(device.last_seen_at)}</td>
                <td>
                    <button class="mini-button" type="button" data-action="edit" data-id="${device.id}">编辑</button>
                    <button class="mini-button danger" type="button" data-action="delete" data-id="${device.id}">删除</button>
                </td>
            </tr>
        `).join("");
    }

    function renderAlerts() {
        const board = document.getElementById("alertsBoard");
        if (!board) return;
        board.innerHTML = state.alerts.length
            ? state.alerts.map(renderAlertCard).join("")
            : `<div class="empty-state">当前没有告警记录。</div>`;
    }

    function renderAlertCard(item) {
        return `
            <article class="alert-item">
                <h3>${helpers.escape(item.meter_id)} · ${helpers.escape(item.anomaly_type)}</h3>
                <p>${helpers.escape(item.device_name)} / ${helpers.escape(item.location || "")}</p>
                <p>${helpers.escape(item.description)}</p>
                <p>异常分数 ${helpers.formatNumber(item.score, 4)}，阈值 ${helpers.formatNumber(item.threshold, 4)}</p>
                <p>${helpers.formatDate(item.created_at)}</p>
            </article>
        `;
    }

    async function renderHistory() {
        const select = document.getElementById("meterSelect");
        const url = new URL(apiUrl, window.location.origin);
        if (select && select.value) url.searchParams.set("meter_id", select.value);
        const data = await loadJson(url.toString());
        document.getElementById("historyRows").innerHTML = data.rows.length
            ? data.rows.map((row) => `
                <tr>
                    <td>${helpers.formatDate(row.timestamp)}</td>
                    <td>${helpers.escape(row.meter_id)}<br><small>${helpers.escape(row.device_name)}</small></td>
                    <td>${helpers.formatNumber(row.instant_flow, 4)}</td>
                    <td>${helpers.formatNumber(row.cumulative_usage, 2)}</td>
                    <td>${helpers.formatNumber(row.battery_voltage, 2)}</td>
                    <td>${helpers.formatNumber(row.signal_strength, 1)}</td>
                    <td>${helpers.formatNumber(row.temperature, 2)}</td>
                    <td>${helpers.formatNumber(row.pressure, 3)}</td>
                    <td>${helpers.flagText(row.predicted_label)}</td>
                </tr>
            `).join("")
            : `<tr><td colspan="9" class="empty-state">暂无历史数据</td></tr>`;
    }

    function renderSettings() {
        const data = state.settings;
        if (!data) return;
        document.getElementById("settingsGrid").innerHTML = `
            <article class="panel">
                <div class="panel-head"><h2>数据库配置</h2></div>
                <div class="settings-list">
                    <div><span>当前连接</span><strong>${helpers.escape(data.database_uri)}</strong></div>
                    <div><span>SQLite 文件</span><strong>${helpers.escape(data.database_file)}</strong></div>
                    <div><span>WebSocket</span><strong>${helpers.escape(data.websocket_url)}</strong></div>
                </div>
            </article>
            <article class="panel">
                <div class="panel-head"><h2>管理员密文</h2></div>
                <div class="settings-list">
                    <div><span>管理员账号</span><strong>${helpers.escape(data.default_admin.username)}</strong></div>
                    <div><span>对称加密后的密码</span><strong>${helpers.escape(data.default_admin.password_encrypted)}</strong></div>
                </div>
            </article>
            <article class="panel wide">
                <div class="panel-head"><h2>设备 API Key</h2></div>
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>设备编号</th><th>API Key</th></tr></thead>
                        <tbody>
                            ${data.sample_keys.map((item) => `<tr><td>${helpers.escape(item.meter_id)}</td><td><code>${helpers.escape(item.api_key)}</code></td></tr>`).join("")}
                        </tbody>
                    </table>
                </div>
            </article>
        `;
    }

    function drawChart(points) {
        const chartCanvas = document.getElementById("trendChart");
        if (!chartCanvas) return;
        const ctx = chartCanvas.getContext("2d");
        const width = chartCanvas.clientWidth;
        const height = chartCanvas.height;
        chartCanvas.width = width;
        ctx.clearRect(0, 0, width, height);

        if (!points.length) {
            ctx.fillStyle = "#5f6c7b";
            ctx.fillText("暂无图表数据", 20, 40);
            return;
        }

        const padding = 24;
        const values = points.map((item) => item.instant_flow);
        const scores = points.map((item) => item.score);
        const maxValue = Math.max(...values, 0.5);
        const maxScore = Math.max(...scores, 1);

        drawLine(ctx, values, maxValue, "#b45309", padding, width, height);
        drawLine(ctx, scores, maxScore, "#b42318", padding, width, height);
    }

    function drawLine(ctx, series, maxValue, color, padding, width, height) {
        ctx.beginPath();
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = color;
        series.forEach((value, index) => {
            const x = padding + (index / Math.max(1, series.length - 1)) * (width - padding * 2);
            const y = height - padding - (value / maxValue) * (height - padding * 2);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }

    async function saveDevice(event) {
        event.preventDefault();
        const id = document.getElementById("deviceId").value;
        const payload = {
            meter_id: document.getElementById("meterIdInput").value.trim(),
            name: document.getElementById("deviceNameInput").value.trim(),
            location: document.getElementById("deviceLocationInput").value.trim(),
            api_key: document.getElementById("deviceApiKeyInput").value.trim(),
        };
        const method = id ? "PUT" : "POST";
        const targetUrl = id ? `/api/devices/${id}` : "/api/devices";
        await loadJson(targetUrl, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        resetDeviceForm();
    }

    function resetDeviceForm() {
        document.getElementById("deviceId").value = "";
        document.getElementById("deviceForm").reset();
    }

    async function handleDeviceActions(event) {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const id = button.dataset.id;
        const device = state.devices.find((item) => String(item.id) === id);
        if (!device) return;

        if (button.dataset.action === "edit") {
            document.getElementById("deviceId").value = device.id;
            document.getElementById("meterIdInput").value = device.meter_id;
            document.getElementById("deviceNameInput").value = device.name;
            document.getElementById("deviceLocationInput").value = device.location;
            document.getElementById("deviceApiKeyInput").value = device.api_key;
            return;
        }

        if (button.dataset.action === "delete") {
            if (!window.confirm(`确认删除设备 ${device.meter_id}？`)) return;
            await loadJson(`/api/devices/${id}`, { method: "DELETE" });
        }
    }

    async function controlSimulator(action) {
        state.simulator = await loadJson("/api/simulator", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action }),
        });
        renderSimulatorStatus();
    }

    function renderSimulatorStatus() {
        const label = document.getElementById("simStatusText");
        if (!label || !state.simulator) return;
        label.textContent = state.simulator.running
            ? `模拟器运行中，间隔 ${state.simulator.interval_seconds} 秒`
            : "模拟器已停止";
    }

    bootstrap().then(connectWebSocket);

    const deviceForm = document.getElementById("deviceForm");
    if (deviceForm) deviceForm.addEventListener("submit", saveDevice);
    const resetButton = document.getElementById("deviceFormReset");
    if (resetButton) resetButton.addEventListener("click", resetDeviceForm);
    const devicesTableBody = document.getElementById("devicesTableBody");
    if (devicesTableBody) devicesTableBody.addEventListener("click", handleDeviceActions);
    const historyButton = document.getElementById("historyRefreshButton");
    if (historyButton) historyButton.addEventListener("click", renderHistory);
    const meterSelect = document.getElementById("meterSelect");
    if (meterSelect) meterSelect.addEventListener("change", renderHistory);
    const simStart = document.getElementById("simStartBtn");
    if (simStart) simStart.addEventListener("click", () => controlSimulator("start"));
    const simStop = document.getElementById("simStopBtn");
    if (simStop) simStop.addEventListener("click", () => controlSimulator("stop"));
}
