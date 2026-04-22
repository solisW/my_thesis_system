const root = document.querySelector("[data-page]");

if (root) {
    const page = root.dataset.page;
    const wsUrl = root.dataset.wsUrl;
    const state = {
        dashboard: null,
        devices: [],
        engineers: [],
        workOrders: [],
        alerts: [],
        reports: null,
        settings: null,
        simulator: null,
        alertSort: "time",
        mapFilter: "all",
        selectedWorkOrderId: null,
    };

    let renderQueued = false;
    let socket = null;
    let leafletMap = null;
    let leafletLayer = null;

    const helpers = {
        text(value) {
            return String(value ?? "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;");
        },
        number(value, digits = 2) {
            if (value === undefined || value === null || Number.isNaN(Number(value))) return "-";
            return Number(value).toFixed(digits);
        },
        date(value) {
            if (!value) return "-";
            return new Date(value).toLocaleString("zh-CN", { hour12: false });
        },
        deviceStatus(status) {
            const labels = { online: "在线", offline: "离线" };
            return `<span class="status-tag ${status}">${labels[status] || status}</span>`;
        },
        engineerStatus(status) {
            const labels = { available: "空闲", busy: "忙碌", offline: "离岗" };
            return `<span class="status-tag ${status}">${labels[status] || status}</span>`;
        },
        orderPriority(priority) {
            const labels = { high: "高", medium: "中", low: "低" };
            return `<span class="priority-tag ${priority}">${labels[priority] || priority}</span>`;
        },
        orderStatus(status) {
            const labels = { pending: "待受理", assigned: "已派单", in_progress: "处理中", completed: "已完成" };
            return `<span class="status-tag ${status}">${labels[status] || status}</span>`;
        },
        anomalyText(flag) {
            return flag ? '<span class="alarm-text">异常</span>' : '<span class="normal-text">正常</span>';
        },
        severityText(severity) {
            const labels = { high: "紧急", medium: "重要", low: "一般" };
            return labels[severity] || severity || "-";
        },
        stageText(stage) {
            const labels = { pending: "待受理", assigned: "已派单", in_progress: "处理中", completed: "已完成" };
            return labels[stage] || stage || "-";
        },
    };

    function queueRender() {
        if (renderQueued) return;
        renderQueued = true;
        requestAnimationFrame(() => {
            renderQueued = false;
            renderPage();
        });
    }

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || `请求失败: ${response.status}`);
        return payload;
    }

    function connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${protocol}://${window.location.host}${wsUrl}`);
        socket.addEventListener("open", () => socket.send("bootstrap"));
        socket.addEventListener("message", (event) => {
            const message = JSON.parse(event.data);
            if (message.event === "bootstrap") {
                Object.entries(message.data).forEach(([eventName, payload]) => applyEvent(eventName, payload));
                return;
            }
            applyEvent(message.event, message.data);
        });
        socket.addEventListener("close", () => setTimeout(connectWebSocket, 1500));
    }

    function applyEvent(eventName, payload) {
        if (eventName === "dashboard") {
            state.dashboard = payload;
            if (page === "dashboard") queueRender();
            return;
        }
        if (eventName === "devices") state.devices = payload;
        if (eventName === "engineers") state.engineers = payload;
        if (eventName === "work_orders") state.workOrders = payload;
        if (eventName === "alerts") state.alerts = payload;
        if (eventName === "reports") state.reports = payload;
        if (eventName === "settings") state.settings = payload;
        if (["devices", "engineers", "work_orders", "alerts", "reports", "settings"].includes(eventName)) {
            queueRender();
        }
    }

    async function bootstrapPage() {
        if (page === "dashboard") {
            state.dashboard = await requestJson("/api/dashboard");
            state.alerts = state.dashboard.alerts || [];
        }
        if (page === "devices") state.devices = await requestJson("/api/devices");
        if (page === "engineers") state.engineers = await requestJson("/api/engineers");
        if (page === "work_orders") state.workOrders = await requestJson("/api/work-orders");
        if (page === "alerts") state.alerts = await requestJson(`/api/alerts?limit=50&sort_by=${encodeURIComponent(state.alertSort)}`);
        if (page === "reports") state.reports = await requestJson("/api/reports");
        if (page === "settings") {
            state.settings = await requestJson("/api/settings");
            state.simulator = await requestJson("/api/simulator");
        }
        if (page === "history") await refreshHistory();
        connectWebSocket();
        queueRender();
    }

    function renderPage() {
        if (page === "dashboard") renderDashboard();
        if (page === "devices") renderDevices();
        if (page === "engineers") renderEngineers();
        if (page === "work_orders") renderWorkOrders();
        if (page === "alerts") renderAlerts();
        if (page === "reports") renderReports();
        if (page === "settings") renderSettings();
    }

    function sortAlerts(items, mode) {
        const copy = [...items];
        if (mode === "severity") {
            const rank = { high: 0, medium: 1, low: 2 };
            return copy.sort((a, b) => {
                const delta = (rank[a.severity] ?? 99) - (rank[b.severity] ?? 99);
                if (delta !== 0) return delta;
                return new Date(b.created_at) - new Date(a.created_at);
            });
        }
        return copy.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    }

    function filterMapPoints(points) {
        if (state.mapFilter === "online") return points.filter((item) => item.status === "online" && !item.anomaly);
        if (state.mapFilter === "anomaly") return points.filter((item) => item.anomaly);
        if (state.mapFilter === "offline") return points.filter((item) => item.status === "offline");
        return points;
    }

    function mapPointClass(point) {
        if (point.anomaly) return "alarm";
        if (point.status === "offline") return "offline";
        return "healthy";
    }

    function renderDashboard() {
        if (!state.dashboard) return;
        const summary = state.dashboard.summary;
        document.getElementById("connectedCount").textContent = summary.connected_devices;
        document.getElementById("offlineCount").textContent = summary.offline_devices;
        document.getElementById("abnormalCount").textContent = summary.abnormal_devices;
        document.getElementById("totalCount").textContent = summary.total_devices;

        const sortSelect = document.getElementById("dashboardAlertSort");
        if (sortSelect) sortSelect.value = state.alertSort;
        const alerts = sortAlerts(state.alerts || [], state.alertSort).slice(0, 6);
        document.getElementById("dashboardAlerts").innerHTML = renderAlertCards(alerts, "暂无告警");

        document.getElementById("dashboardDevices").innerHTML = (state.dashboard.device_cards || [])
            .map((item) => `
                <tr>
                    <td>${helpers.text(item.meter_id)}<br><small>${helpers.text(item.name)}</small></td>
                    <td>${helpers.text(item.location)}</td>
                    <td>${helpers.deviceStatus(item.status)}</td>
                    <td class="${item.anomaly ? "alarm-cell" : ""}">${helpers.number(item.instant_flow, 4)}<br><small>${helpers.anomalyText(item.anomaly)}</small></td>
                    <td>${helpers.number(item.signal_strength, 1)}</td>
                    <td>${helpers.number(item.battery_voltage, 2)} V</td>
                    <td>${helpers.date(item.updated_at)}</td>
                </tr>
            `)
            .join("");

        renderMap(state.dashboard.map_points || []);
        updateMapFilterButtons();
    }

    function renderMap(points) {
        const container = document.getElementById("mapBoard");
        if (!container) return;
        const filtered = filterMapPoints(points);

        if (window.L) {
            if (!leafletMap) {
                leafletMap = L.map(container, { zoomControl: true, scrollWheelZoom: false }).setView([31.2304, 121.4737], 13);
                L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                    maxZoom: 19,
                    attribution: "&copy; OpenStreetMap contributors",
                }).addTo(leafletMap);
                leafletLayer = L.layerGroup().addTo(leafletMap);
            }
            leafletLayer.clearLayers();
            const bounds = [];
            filtered.forEach((point) => {
                const icon = L.divIcon({
                    className: "",
                    html: `<div class="leaflet-device-marker ${mapPointClass(point)}">${helpers.text(point.meter_id)}</div>`,
                    iconSize: [72, 32],
                    iconAnchor: [36, 16],
                });
                const lat = point.display_latitude ?? point.latitude;
                const lng = point.display_longitude ?? point.longitude;
                const marker = L.marker([lat, lng], { icon });
                marker.bindPopup(`
                    <div class="map-popup">
                        <strong>${helpers.text(point.meter_id)}</strong>
                        <span>${helpers.text(point.name)}</span>
                        <span>地址：${helpers.text(point.location)}</span>
                        <span>坐标：${helpers.number(point.latitude, 5)}, ${helpers.number(point.longitude, 5)}</span>
                    </div>
                `);
                marker.addTo(leafletLayer);
                bounds.push([lat, lng]);
            });
            if (bounds.length > 1) {
                leafletMap.fitBounds(bounds, { padding: [28, 28], maxZoom: 15 });
            } else if (bounds.length === 1) {
                leafletMap.setView(bounds[0], 15);
            } else {
                leafletMap.setView([31.2304, 121.4737], 13);
            }
            setTimeout(() => leafletMap && leafletMap.invalidateSize(), 0);
            return;
        }

        const xs = filtered.map((item) => item.display_longitude ?? item.longitude);
        const ys = filtered.map((item) => item.display_latitude ?? item.latitude);
        const minLat = Math.min(...ys, 31.228);
        const maxLat = Math.max(...ys, 31.256);
        const minLng = Math.min(...xs, 121.47);
        const maxLng = Math.max(...xs, 121.515);
        container.innerHTML = `
            <div class="map-grid">
                ${filtered
                    .map((item) => {
                        const x = item.display_longitude ?? item.longitude;
                        const y = item.display_latitude ?? item.latitude;
                        const left = ((x - minLng) / Math.max(0.001, maxLng - minLng)) * 100;
                        const top = 100 - ((y - minLat) / Math.max(0.001, maxLat - minLat)) * 100;
                        return `<button class="map-marker ${mapPointClass(item)}" style="left:${left}%;top:${top}%;" title="${helpers.text(item.meter_id)} ${helpers.text(item.location)}"><span>${helpers.text(item.meter_id)}</span></button>`;
                    })
                    .join("")}
                <div class="map-legend">
                    <span><i class="dot healthy"></i>在线正常</span>
                    <span><i class="dot alarm"></i>异常设备</span>
                    <span><i class="dot offline"></i>离线设备</span>
                </div>
            </div>
        `;
    }

    function renderTrendChart(points) {
        const canvas = document.getElementById("trendChart");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const ratio = window.devicePixelRatio || 1;
        const width = canvas.clientWidth || 520;
        const height = Math.max(380, canvas.clientHeight || 380);
        canvas.width = Math.floor(width * ratio);
        canvas.height = Math.floor(height * ratio);
        canvas.style.height = `${height}px`;
        ctx.scale(ratio, ratio);
        ctx.clearRect(0, 0, width, height);

        if (!points.length) {
            ctx.fillStyle = "#6b7280";
            ctx.font = "14px Microsoft YaHei, sans-serif";
            ctx.fillText("暂无异常趋势数据", 24, 44);
            return;
        }

        const padding = { top: 20, right: 18, bottom: 46, left: 42 };
        const innerWidth = width - padding.left - padding.right;
        const innerHeight = height - padding.top - padding.bottom;
        const maxValue = Math.max(1, ...points.map((item) => item.anomaly_count));
        const barWidth = innerWidth / Math.max(1, points.length);
        const barColor = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
        barColor.addColorStop(0, "rgba(220, 38, 38, 0.92)");
        barColor.addColorStop(1, "rgba(201, 95, 24, 0.88)");

        ctx.strokeStyle = "rgba(24, 33, 43, 0.08)";
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i += 1) {
            const y = padding.top + (innerHeight / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(width - padding.right, y);
            ctx.stroke();
        }

        points.forEach((item, index) => {
            const x = padding.left + index * barWidth + barWidth * 0.18;
            const barHeight = (item.anomaly_count / maxValue) * innerHeight;
            const y = padding.top + innerHeight - barHeight;
            ctx.fillStyle = barColor;
            ctx.fillRect(x, y, barWidth * 0.64, barHeight);
            if (index % Math.max(1, Math.ceil(points.length / 8)) === 0) {
                ctx.save();
                ctx.fillStyle = "#5d6b79";
                ctx.font = "11px Microsoft YaHei, sans-serif";
                ctx.translate(x + barWidth * 0.32, height - 16);
                ctx.rotate(-Math.PI / 6);
                ctx.textAlign = "right";
                ctx.fillText(item.label, 0, 0);
                ctx.restore();
            }
        });

        ctx.fillStyle = "#18212b";
        ctx.font = "12px Microsoft YaHei, sans-serif";
        ctx.fillText("异常数量", 4, 14);
    }

    function renderAlertCards(items, emptyText) {
        return items.length
            ? items.map((item) => `
                <article class="alert-card ${item.severity}">
                    <h3>${helpers.text(item.meter_id)} · ${helpers.text(item.anomaly_type)}</h3>
                    <p>${helpers.text(item.location)}</p>
                    <p>${helpers.text(item.description)}</p>
                    <div class="alert-meta">
                        <span>${helpers.severityText(item.severity)}</span>
                        <span>分数 ${helpers.number(item.score, 4)}</span>
                    </div>
                    <time>${helpers.date(item.created_at)}</time>
                </article>
            `).join("")
            : `<div class="empty-block">${helpers.text(emptyText)}</div>`;
    }

    async function updateAlertSort(event) {
        state.alertSort = event.target.value;
        if (page === "dashboard" || page === "alerts") {
            state.alerts = await requestJson(`/api/alerts?limit=50&sort_by=${encodeURIComponent(state.alertSort)}`);
        }
        queueRender();
    }

    function updateMapFilter(event) {
        const button = event.target.closest("button[data-map-filter]");
        if (!button) return;
        state.mapFilter = button.dataset.mapFilter;
        queueRender();
    }

    function updateMapFilterButtons() {
        document.querySelectorAll("button[data-map-filter]").forEach((button) => {
            button.classList.toggle("active", button.dataset.mapFilter === state.mapFilter);
        });
    }

    window.addEventListener("resize", () => {
        if (page === "dashboard" && leafletMap) {
            requestAnimationFrame(() => leafletMap.invalidateSize());
        }
    });

    function renderDevices() {
        const tbody = document.getElementById("deviceTable");
        if (!tbody) return;
        tbody.innerHTML = state.devices
            .map(
                (device) => `
            <tr>
                <td>${helpers.text(device.meter_id)}</td>
                <td>${helpers.text(device.name)}</td>
                <td>${helpers.text(device.location)}</td>
                <td>${helpers.text(device.device_mode === "physical" ? "真实设备" : "模拟设备")}</td>
                <td>${helpers.deviceStatus(device.status)}</td>
                <td>${device.open_orders}</td>
                <td>${helpers.date(device.last_seen_at)}</td>
                <td class="action-cell">
                    <button class="mini-button" data-action="edit-device" data-id="${device.id}">编辑</button>
                    <button class="mini-button" data-action="test-device" data-id="${device.id}">测试</button>
                    <button class="mini-button danger" data-action="delete-device" data-id="${device.id}">删除</button>
                </td>
            </tr>
        `
            )
            .join("");
        syncWorkOrderDeviceOptions();
    }

    function renderEngineers() {
        const tbody = document.getElementById("engineerTable");
        if (!tbody) return;
        tbody.innerHTML = state.engineers
            .map(
                (engineer) => `
            <tr>
                <td>${helpers.text(engineer.name)}</td>
                <td>${helpers.text(engineer.phone)}</td>
                <td>${helpers.text(engineer.specialty)}</td>
                <td>${helpers.engineerStatus(engineer.status)}</td>
                <td>${helpers.text(engineer.region)}</td>
                <td>${engineer.active_orders}</td>
                <td class="action-cell">
                    <button class="mini-button" data-action="edit-engineer" data-id="${engineer.id}">编辑</button>
                    <button class="mini-button danger" data-action="delete-engineer" data-id="${engineer.id}">删除</button>
                </td>
            </tr>
        `
            )
            .join("");
        syncWorkOrderEngineerOptions();
    }

    function renderWorkOrders() {
        const tbody = document.getElementById("workOrderTable");
        if (!tbody) return;
        if (!state.selectedWorkOrderId && state.workOrders.length) state.selectedWorkOrderId = state.workOrders[0].id;
        syncWorkOrderDeviceOptions();
        syncWorkOrderEngineerOptions();
        tbody.innerHTML = state.workOrders
            .map(
                (order) => `
            <tr class="${String(order.id) === String(state.selectedWorkOrderId) ? "selected-row" : ""}">
                <td>${helpers.text(order.title)}</td>
                <td>${helpers.text(order.meter_id)}<br><small>${helpers.text(order.device_name)}</small></td>
                <td>${helpers.text(order.engineer_name)}</td>
                <td>${helpers.orderPriority(order.priority)}</td>
                <td>${helpers.orderStatus(order.status)}</td>
                <td>${helpers.stageText(order.current_stage)}</td>
                <td>${helpers.date(order.updated_at)}</td>
                <td class="action-cell">
                    <button class="mini-button" data-action="view-order" data-id="${order.id}">记录</button>
                    <button class="mini-button" data-action="edit-order" data-id="${order.id}">编辑</button>
                    <button class="mini-button danger" data-action="delete-order" data-id="${order.id}">删除</button>
                </td>
            </tr>
        `
            )
            .join("");
        renderWorkOrderDetail();
    }

    function renderWorkOrderDetail() {
        const board = document.getElementById("workOrderDetail");
        if (!board) return;
        const order = state.workOrders.find((item) => String(item.id) === String(state.selectedWorkOrderId)) || state.workOrders[0];
        if (!order) {
            board.innerHTML = '<div class="empty-block">暂无工单记录</div>';
            return;
        }
        state.selectedWorkOrderId = order.id;
        const records = order.records || [];
        board.innerHTML = `
            <div class="detail-head">
                <div>
                    <p class="eyebrow">Flow</p>
                    <h3>${helpers.text(order.title)}</h3>
                    <p class="subtle">${helpers.text(order.description)}</p>
                </div>
                <div class="detail-badges">
                    ${helpers.orderPriority(order.priority)}
                    ${helpers.orderStatus(order.status)}
                </div>
            </div>
            <div class="flow-rail">
                ${(order.flow_nodes || []).map((node) => `
                    <div class="flow-node ${node.active ? "active" : ""} ${node.current ? "current" : ""}">
                        <span>${helpers.stageText(node.stage)}</span>
                        <strong>${node.current ? "当前节点" : node.active ? "已到达" : "待处理"}</strong>
                    </div>
                `).join("")}
            </div>
            <div class="record-list">
                ${records.length ? records.map((record) => `
                    <article class="record-card">
                        <div class="record-top">
                            <strong>${helpers.stageText(record.stage)}</strong>
                            <span>${helpers.date(record.created_at)}</span>
                        </div>
                        <p>${helpers.text(record.action)}</p>
                        <p class="subtle">${helpers.text(record.note)}</p>
                        <small>${helpers.text(record.operator_name)}</small>
                    </article>
                `).join("") : '<div class="empty-block">当前工单暂无处理记录</div>'}
            </div>
        `;
    }

    function renderAlerts() {
        const board = document.getElementById("alertCards");
        if (!board) return;
        const select = document.getElementById("alertSortSelect");
        if (select) select.value = state.alertSort;
        board.innerHTML = renderAlertCards(sortAlerts(state.alerts || [], state.alertSort), "暂无告警数据");
    }

    function renderReports() {
        if (!state.reports) return;
        document.getElementById("reportTotalOrders").textContent = state.reports.order_summary.total_orders;
        document.getElementById("reportOpenOrders").textContent = state.reports.order_summary.open_orders;
        document.getElementById("reportCompletedOrders").textContent = state.reports.order_summary.completed_orders;
        document.getElementById("severitySummary").innerHTML = `
            <div><span>高等级告警</span><strong>${state.reports.severity_summary.high}</strong></div>
            <div><span>中等级告警</span><strong>${state.reports.severity_summary.medium}</strong></div>
            <div><span>低等级告警</span><strong>${state.reports.severity_summary.low}</strong></div>
        `;
    }

    async function refreshHistory() {
        const select = document.getElementById("historyMeterSelect");
        if (!select) return;
        const meterId = select.value;
        const url = meterId ? `/api/history?meter_id=${encodeURIComponent(meterId)}` : "/api/history";
        const data = await requestJson(url);
        document.getElementById("historyTable").innerHTML = data.rows.length
            ? data.rows
                .map(
                    (row) => `
                <tr>
                    <td>${helpers.date(row.timestamp)}</td>
                    <td>${helpers.text(row.meter_id)}<br><small>${helpers.text(row.device_name)}</small></td>
                    <td>${helpers.number(row.instant_flow, 4)}</td>
                    <td>${helpers.number(row.cumulative_usage, 2)}</td>
                    <td>${helpers.number(row.signal_strength, 1)}</td>
                    <td>${helpers.number(row.battery_voltage, 2)} V</td>
                    <td>${helpers.anomalyText(row.predicted_label === 1)}</td>
                </tr>
            `
                )
                .join("")
            : '<tr><td colspan="7">暂无历史数据</td></tr>';
    }

    function renderSettings() {
        const board = document.getElementById("settingsBoard");
        if (board && state.settings) {
            board.innerHTML = `
                <div><span>数据库连接</span><strong>${helpers.text(state.settings.database_uri)}</strong></div>
                <div><span>模拟设备数量</span><strong>${state.settings.simulation_device_count}</strong></div>
                <div><span>上传接口</span><strong>${helpers.text(state.settings.device_upload_api)}</strong></div>
                <div><span>WebSocket</span><strong>${helpers.text(state.settings.websocket_url)}</strong></div>
            `;
        }
        const label = document.getElementById("simulatorStatus");
        if (label && state.simulator) {
            label.textContent = state.simulator.running ? `模拟器运行中，间隔 ${state.simulator.interval_seconds} 秒` : "模拟器已停止";
        }
    }

    function syncWorkOrderDeviceOptions() {
        const select = document.getElementById("workOrderDevice");
        if (!select) return;
        const current = select.value;
        select.innerHTML = state.devices.map((item) => `<option value="${item.id}">${helpers.text(item.meter_id)} - ${helpers.text(item.name)}</option>`).join("");
        if (current) select.value = current;
    }

    function syncWorkOrderEngineerOptions() {
        const select = document.getElementById("workOrderEngineer");
        if (!select) return;
        const current = select.value;
        select.innerHTML = `<option value="">未分配</option>${state.engineers
            .map((item) => `<option value="${item.id}">${helpers.text(item.name)} / ${helpers.text(item.region)}</option>`)
            .join("")}`;
        if (current) select.value = current;
    }

    function resetForm(formId, hiddenId) {
        const form = document.getElementById(formId);
        if (form) form.reset();
        const hidden = document.getElementById(hiddenId);
        if (hidden) hidden.value = "";
    }

    async function saveDevice(event) {
        event.preventDefault();
        const deviceId = document.getElementById("deviceId").value;
        const payload = {
            meter_id: document.getElementById("deviceMeterId").value.trim(),
            name: document.getElementById("deviceName").value.trim(),
            location: document.getElementById("deviceLocation").value.trim(),
            area: document.getElementById("deviceArea").value.trim(),
            latitude: document.getElementById("deviceLatitude").value,
            longitude: document.getElementById("deviceLongitude").value,
            device_mode: document.getElementById("deviceMode").value,
            protocol: document.getElementById("deviceProtocol").value.trim(),
            ip_address: document.getElementById("deviceIp").value.trim(),
            port: document.getElementById("devicePort").value,
            firmware_version: document.getElementById("deviceFirmware").value.trim(),
            api_key: document.getElementById("deviceApiKey").value.trim(),
        };
        await requestJson(deviceId ? `/api/devices/${deviceId}` : "/api/devices", {
            method: deviceId ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        resetForm("deviceForm", "deviceId");
    }

    async function saveEngineer(event) {
        event.preventDefault();
        const engineerId = document.getElementById("engineerId").value;
        const payload = {
            name: document.getElementById("engineerName").value.trim(),
            phone: document.getElementById("engineerPhone").value.trim(),
            specialty: document.getElementById("engineerSpecialty").value.trim(),
            region: document.getElementById("engineerRegion").value.trim(),
            status: document.getElementById("engineerStatus").value,
        };
        await requestJson(engineerId ? `/api/engineers/${engineerId}` : "/api/engineers", {
            method: engineerId ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        resetForm("engineerForm", "engineerId");
    }

    async function saveWorkOrder(event) {
        event.preventDefault();
        const orderId = document.getElementById("workOrderId").value;
        const payload = {
            title: document.getElementById("workOrderTitle").value.trim(),
            description: document.getElementById("workOrderDescription").value.trim(),
            priority: document.getElementById("workOrderPriority").value,
            status: document.getElementById("workOrderStatus").value,
            device_id: document.getElementById("workOrderDevice").value,
            engineer_id: document.getElementById("workOrderEngineer").value,
        };
        await requestJson(orderId ? `/api/work-orders/${orderId}` : "/api/work-orders", {
            method: orderId ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        resetForm("workOrderForm", "workOrderId");
        state.selectedWorkOrderId = null;
    }

    async function handleAction(event) {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const action = button.dataset.action;
        const id = button.dataset.id;

        if (action === "edit-device") {
            const device = state.devices.find((item) => String(item.id) === id);
            if (!device) return;
            document.getElementById("deviceId").value = device.id;
            document.getElementById("deviceMeterId").value = device.meter_id;
            document.getElementById("deviceName").value = device.name;
            document.getElementById("deviceLocation").value = device.location;
            document.getElementById("deviceArea").value = device.area;
            document.getElementById("deviceLatitude").value = device.latitude;
            document.getElementById("deviceLongitude").value = device.longitude;
            document.getElementById("deviceMode").value = device.device_mode;
            document.getElementById("deviceProtocol").value = device.protocol;
            document.getElementById("deviceIp").value = device.ip_address || "";
            document.getElementById("devicePort").value = device.port || "";
            document.getElementById("deviceFirmware").value = device.firmware_version;
            document.getElementById("deviceApiKey").value = device.api_key;
        }

        if (action === "delete-device") {
            if (!window.confirm("确认删除该设备？")) return;
            await requestJson(`/api/devices/${id}`, { method: "DELETE" });
        }

        if (action === "test-device") {
            const result = await requestJson(`/api/devices/${id}/connectivity-test`, { method: "POST" });
            window.alert(result.message);
        }

        if (action === "edit-engineer") {
            const engineer = state.engineers.find((item) => String(item.id) === id);
            if (!engineer) return;
            document.getElementById("engineerId").value = engineer.id;
            document.getElementById("engineerName").value = engineer.name;
            document.getElementById("engineerPhone").value = engineer.phone;
            document.getElementById("engineerSpecialty").value = engineer.specialty;
            document.getElementById("engineerRegion").value = engineer.region;
            document.getElementById("engineerStatus").value = engineer.status;
        }

        if (action === "delete-engineer") {
            if (!window.confirm("确认删除该工程师？")) return;
            await requestJson(`/api/engineers/${id}`, { method: "DELETE" });
        }

        if (action === "view-order") {
            state.selectedWorkOrderId = Number(id);
            queueRender();
        }

        if (action === "edit-order") {
            const order = state.workOrders.find((item) => String(item.id) === id);
            if (!order) return;
            state.selectedWorkOrderId = order.id;
            document.getElementById("workOrderId").value = order.id;
            document.getElementById("workOrderTitle").value = order.title;
            document.getElementById("workOrderDescription").value = order.description;
            document.getElementById("workOrderPriority").value = order.priority;
            document.getElementById("workOrderStatus").value = order.status;
            document.getElementById("workOrderDevice").value = String(order.device_id);
            document.getElementById("workOrderEngineer").value = order.engineer_id ? String(order.engineer_id) : "";
            queueRender();
        }

        if (action === "delete-order") {
            if (!window.confirm("确认删除该工单？")) return;
            await requestJson(`/api/work-orders/${id}`, { method: "DELETE" });
        }
    }

    function updateMapFilter(event) {
        const button = event.target.closest("button[data-map-filter]");
        if (!button) return;
        state.mapFilter = button.dataset.mapFilter;
        queueRender();
    }

    function updateMapFilterButtons() {
        document.querySelectorAll("button[data-map-filter]").forEach((button) => {
            button.classList.toggle("active", button.dataset.mapFilter === state.mapFilter);
        });
    }

    async function toggleSimulator(action) {
        state.simulator = await requestJson("/api/simulator", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action }),
        });
        renderSettings();
    }

    const deviceForm = document.getElementById("deviceForm");
    if (deviceForm) deviceForm.addEventListener("submit", saveDevice);
    const engineerForm = document.getElementById("engineerForm");
    if (engineerForm) engineerForm.addEventListener("submit", saveEngineer);
    const workOrderForm = document.getElementById("workOrderForm");
    if (workOrderForm) workOrderForm.addEventListener("submit", saveWorkOrder);
    const deviceReset = document.getElementById("deviceReset");
    if (deviceReset) deviceReset.addEventListener("click", () => resetForm("deviceForm", "deviceId"));
    const engineerReset = document.getElementById("engineerReset");
    if (engineerReset) engineerReset.addEventListener("click", () => resetForm("engineerForm", "engineerId"));
    const workOrderReset = document.getElementById("workOrderReset");
    if (workOrderReset) {
        workOrderReset.addEventListener("click", () => {
            resetForm("workOrderForm", "workOrderId");
            state.selectedWorkOrderId = state.workOrders[0]?.id || null;
            queueRender();
        });
    }
    const historyRefresh = document.getElementById("historyRefresh");
    if (historyRefresh) historyRefresh.addEventListener("click", refreshHistory);
    const historySelect = document.getElementById("historyMeterSelect");
    if (historySelect) historySelect.addEventListener("change", refreshHistory);
    const simStart = document.getElementById("simulatorStart");
    if (simStart) simStart.addEventListener("click", () => toggleSimulator("start"));
    const simStop = document.getElementById("simulatorStop");
    if (simStop) simStop.addEventListener("click", () => toggleSimulator("stop"));
    const alertSortSelect = document.getElementById("alertSortSelect");
    if (alertSortSelect) {
        state.alertSort = alertSortSelect.value || "time";
        alertSortSelect.addEventListener("change", updateAlertSort);
    }
    const dashboardAlertSort = document.getElementById("dashboardAlertSort");
    if (dashboardAlertSort) {
        state.alertSort = dashboardAlertSort.value || state.alertSort;
        dashboardAlertSort.addEventListener("change", updateAlertSort);
    }
    const mapControls = document.getElementById("mapBoard");
    if (mapControls) document.body.addEventListener("click", updateMapFilter);
    document.body.addEventListener("click", handleAction);

    bootstrapPage().catch((error) => console.error(error));
}
