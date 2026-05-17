const { createApp, nextTick } = Vue;

const API_BASE = window.API_BASE || "http://127.0.0.1:5000";
const MAP_COORD_SYSTEM = window.MAP_COORD_SYSTEM || "wgs84";
const AMAP_TILE_URL = window.AMAP_TILE_URL || "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";
const AMAP_TILE_SUBDOMAINS = window.AMAP_TILE_SUBDOMAINS || ["1", "2", "3", "4"];
const MAP_CENTER = [31.2304, 121.4737];
const MAP_TILE_ERROR_LIMIT = 6;

function outsideChina(lat, lng) {
    return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(x, y) {
    let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin(y / 3.0 * Math.PI)) * 2.0 / 3.0;
    ret += (160.0 * Math.sin(y / 12.0 * Math.PI) + 320 * Math.sin(y * Math.PI / 30.0)) * 2.0 / 3.0;
    return ret;
}

function transformLng(x, y) {
    let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin(x / 3.0 * Math.PI)) * 2.0 / 3.0;
    ret += (150.0 * Math.sin(x / 12.0 * Math.PI) + 300.0 * Math.sin(x / 30.0 * Math.PI)) * 2.0 / 3.0;
    return ret;
}

function toAmapCoordinate(lat, lng) {
    if (MAP_COORD_SYSTEM === "gcj02" || outsideChina(lat, lng)) return [lat, lng];
    const a = 6378245.0;
    const ee = 0.00669342162296594323;
    let dLat = transformLat(lng - 105.0, lat - 35.0);
    let dLng = transformLng(lng - 105.0, lat - 35.0);
    const radLat = lat / 180.0 * Math.PI;
    let magic = Math.sin(radLat);
    magic = 1 - ee * magic * magic;
    const sqrtMagic = Math.sqrt(magic);
    dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
    dLng = (dLng * 180.0) / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
    return [lat + dLat, lng + dLng];
}

function mapPointCoordinate(point) {
    const lat = Number(point.display_latitude ?? point.latitude);
    const lng = Number(point.display_longitude ?? point.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    return toAmapCoordinate(lat, lng);
}

const pageMeta = [
    { key: "dashboard", label: "综合态势", hint: "实时监控", roles: ["super_admin", "sub_admin", "engineer"] },
    { key: "devices", label: "设备管理", hint: "接入与状态", roles: ["super_admin", "sub_admin"] },
    { key: "alerts", label: "异常告警", hint: "模型研判", roles: ["super_admin", "sub_admin", "engineer"] },
    { key: "work_orders", label: "工单闭环", hint: "派单处置", roles: ["super_admin", "sub_admin", "engineer"] },
    { key: "engineers", label: "工程师", hint: "在线与负载", roles: ["super_admin", "sub_admin"] },
    { key: "history", label: "历史数据", hint: "时序追踪", roles: ["super_admin", "sub_admin", "engineer"] },
    { key: "reports", label: "统计报表", hint: "运营分析", roles: ["super_admin", "sub_admin", "engineer"] },
    { key: "settings", label: "系统设置", hint: "模型与服务", roles: ["super_admin", "sub_admin"] },
    { key: "users", label: "用户权限", hint: "账号体系", roles: ["super_admin"] },
];

function emptyState() {
    return {
        dashboard: null,
        devices: [],
        alerts: [],
        workOrders: [],
        engineers: [],
        users: [],
        reports: null,
        settings: null,
        training: null,
        simulator: null,
        mqtt: null,
        drift: null,
        history: null,
        reconstruction: null,
        labeledSamples: [],
    };
}

function userFormDefaults() {
    return {
        id: "",
        username: "",
        full_name: "",
        password: "",
        role: "engineer",
        is_active: true,
        employee_no: "",
        phone: "",
        region: "",
        address: "",
    };
}

function workOrderDefaults() {
    return {
        id: "",
        title: "",
        description: "",
        region: "",
        priority: "medium",
        status: "pending",
        device_id: "",
        engineer_id: "",
    };
}

function chartGradient(color) {
    return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color },
        { offset: 1, color: "rgba(255,255,255,0.03)" },
    ]);
}

createApp({
    data() {
        return {
            apiBase: API_BASE,
            user: null,
            page: location.hash.replace("#/", "") || "dashboard",
            loginForm: { username: "", password: "" },
            message: "",
            busy: false,
            realtimeText: "连接中",
            state: emptyState(),
            filters: { alertSort: "time", meterId: "" },
            forms: { user: userFormDefaults(), workOrder: workOrderDefaults() },
            socket: null,
            charts: {},
            map: null,
            mapLayer: null,
            mapTileLayer: null,
            mapTileErrors: 0,
        };
    },
    computed: {
        visiblePages() {
            const role = this.user?.role || "guest";
            return pageMeta.filter((item) => item.roles.includes(role));
        },
        currentPage() {
            return pageMeta.find((item) => item.key === this.page) || pageMeta[0];
        },
        canAdmin() {
            return ["super_admin", "sub_admin"].includes(this.user?.role);
        },
        canSuperAdmin() {
            return this.user?.role === "super_admin";
        },
        isEngineer() {
            return this.user?.role === "engineer";
        },
        summary() {
            return this.state.dashboard?.summary || {};
        },
        openOrders() {
            return this.state.workOrders.filter((item) => item.status !== "completed").length;
        },
        filteredWorkOrders() {
            if (!this.isEngineer) return this.state.workOrders;
            return this.state.workOrders.filter((item) => String(item.engineer_id || "") === String(this.user?.engineer_id || ""));
        },
        historyRows() {
            return [...(this.state.history?.rows || [])].reverse();
        },
        activeModel() {
            return this.state.settings?.active_model_id || this.state.settings?.loaded_model_version || "-";
        },
    },
    async mounted() {
        window.addEventListener("hashchange", this.onHashChange);
        window.addEventListener("resize", this.resizeVisuals);
        await this.closeStaleSessionIfNewTab();
        await this.loadSession();
    },
    beforeUnmount() {
        window.removeEventListener("hashchange", this.onHashChange);
        window.removeEventListener("resize", this.resizeVisuals);
        if (this.socket) this.socket.close();
    },
    methods: {
        async closeStaleSessionIfNewTab() {
            const tabKey = "smart-gas-monitor-active-tab";
            if (sessionStorage.getItem(tabKey) === "1") return;
            sessionStorage.setItem(tabKey, "1");
            await fetch(`${this.apiBase}/api/session/close`, {
                method: "POST",
                credentials: "include",
                keepalive: true,
            }).catch(() => null);
        },
        async request(path, options = {}) {
            const response = await fetch(`${this.apiBase}${path}`, {
                credentials: "include",
                headers: { "Content-Type": "application/json", ...(options.headers || {}) },
                ...options,
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.message || `请求失败：${response.status}`);
            return payload;
        },
        async loadSession() {
            try {
                const payload = await this.request("/api/auth/session");
                this.user = payload.user;
                this.ensureAllowedPage();
                await this.loadPage();
                this.connectSocket(payload.ws_url || "/ws");
            } catch {
                this.user = null;
                this.realtimeText = "未登录";
            }
        },
        async login() {
            this.message = "";
            this.busy = true;
            try {
                const payload = await this.request("/api/auth/login", {
                    method: "POST",
                    body: JSON.stringify(this.loginForm),
                });
                this.user = payload.user;
                this.ensureAllowedPage();
                await this.loadPage();
                this.connectSocket(payload.ws_url || "/ws");
            } catch (error) {
                this.message = error.message;
            } finally {
                this.busy = false;
            }
        },
        async logout() {
            await this.request("/api/auth/logout", { method: "POST" }).catch(() => null);
            this.user = null;
            this.state = emptyState();
            this.realtimeText = "未登录";
            if (this.socket) this.socket.close();
        },
        ensureAllowedPage() {
            if (!this.visiblePages.some((item) => item.key === this.page)) {
                this.page = this.visiblePages[0]?.key || "dashboard";
                location.hash = `#/${this.page}`;
            }
        },
        onHashChange() {
            this.page = location.hash.replace("#/", "") || "dashboard";
            this.ensureAllowedPage();
            this.loadPage();
        },
        go(page) {
            location.hash = `#/${page}`;
        },
        async loadPage() {
            if (!this.user) return;
            this.busy = true;
            this.message = "";
            try {
                if (this.page === "dashboard") {
                    this.state.dashboard = await this.request("/api/dashboard");
                    this.state.alerts = this.state.dashboard.alerts || [];
                    this.state.workOrders = await this.request("/api/work-orders");
                    this.stabilizeVisuals(() => this.renderDashboardVisuals());
                }
                if (this.page === "devices") this.state.devices = await this.request("/api/devices");
                if (this.page === "alerts") {
                    this.state.alerts = await this.request(`/api/alerts?limit=50&sort_by=${encodeURIComponent(this.filters.alertSort)}`);
                    if (this.canAdmin) this.state.labeledSamples = await this.request("/api/labeled-samples");
                }
                if (this.page === "work_orders") {
                    if (this.canAdmin) {
                        this.state.devices = await this.request("/api/devices");
                        this.state.engineers = await this.request("/api/engineers");
                    }
                    this.state.workOrders = await this.request("/api/work-orders");
                }
                if (this.page === "engineers") this.state.engineers = await this.request("/api/engineers");
                if (this.page === "users") {
                    this.state.users = await this.request("/api/users");
                    this.state.engineers = await this.request("/api/engineers");
                }
                if (this.page === "history") {
                    this.state.devices = await this.request("/api/devices");
                    await this.loadHistory();
                }
                if (this.page === "reports") {
                    this.state.reports = await this.request("/api/reports");
                    this.stabilizeVisuals(() => this.renderReportChart());
                }
                if (this.page === "settings") {
                    this.state.settings = await this.request("/api/settings");
                    this.state.training = (await this.request("/api/training")).status;
                    this.state.simulator = await this.request("/api/simulator");
                    this.state.mqtt = (await this.request("/api/mqtt")).status;
                    this.state.drift = (await this.request("/api/drift")).status;
                }
            } catch (error) {
                this.message = error.message;
            } finally {
                this.busy = false;
            }
        },
        connectSocket(path) {
            if (this.socket) this.socket.close();
            const base = new URL(this.apiBase);
            const protocol = base.protocol === "https:" ? "wss" : "ws";
            this.socket = new WebSocket(`${protocol}://${base.host}${path}`);
            this.socket.addEventListener("open", () => {
                this.realtimeText = "实时在线";
                this.socket.send("bootstrap");
            });
            this.socket.addEventListener("message", (event) => {
                const message = JSON.parse(event.data);
                if (message.event === "bootstrap") {
                    Object.entries(message.data).forEach(([key, value]) => this.applyRealtime(key, value));
                    return;
                }
                this.applyRealtime(message.event, message.data);
            });
            this.socket.addEventListener("close", () => {
                this.realtimeText = "重连中";
                if (this.user) setTimeout(() => this.connectSocket(path), 1800);
            });
            this.socket.addEventListener("error", () => {
                this.realtimeText = "连接异常";
            });
        },
        applyRealtime(eventName, payload) {
            const mapping = {
                dashboard: "dashboard",
                devices: "devices",
                engineers: "engineers",
                users: "users",
                work_orders: "workOrders",
                alerts: "alerts",
                reports: "reports",
                settings: "settings",
            };
            const key = mapping[eventName];
            if (key) this.state[key] = payload;
            this.stabilizeVisuals(() => {
                if (this.page === "dashboard") this.renderDashboardVisuals();
                if (this.page === "reports") this.renderReportChart();
                if (this.page === "history") this.renderHistoryCharts();
            });
        },
        resizeVisuals() {
            Object.values(this.charts).forEach((chart) => chart?.resize());
            if (this.map) this.map.invalidateSize();
        },
        latest(device) {
            return device?.latest_reading || {};
        },
        number(value, digits = 2) {
            const parsed = Number(value);
            return Number.isFinite(parsed) ? parsed.toFixed(digits) : "-";
        },
        date(value) {
            return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
        },
        shortDate(value) {
            return value ? new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "-";
        },
        roleLabel(role) {
            return { super_admin: "主管理员", sub_admin: "管理员", admin: "管理员", engineer: "工程师" }[role] || role || "-";
        },
        statusLabel(status) {
            return {
                online: "在线",
                offline: "离线",
                pending: "待处理",
                assigned: "已派单",
                in_progress: "处理中",
                completed: "已完成",
                open: "开放",
                available: "空闲",
                busy: "忙碌",
            }[status] || status || "-";
        },
        priorityLabel(priority) {
            return { high: "高优先级", medium: "中优先级", low: "低优先级" }[priority] || priority || "-";
        },
        severityLabel(severity) {
            return { high: "紧急", medium: "重要", low: "一般" }[severity] || severity || "-";
        },
        sampleLabel(label) {
            return { confirmed_anomaly: "真实异常", false_positive: "误报", ignored: "忽略" }[label] || label || "-";
        },
        moduleRunning(module) {
            return Boolean(module?.running);
        },
        async toggleDevice(device) {
            await this.request(`/api/devices/${device.id}`, {
                method: "PUT",
                body: JSON.stringify({ is_enabled: !device.is_enabled }),
            });
            await this.loadPage();
        },
        async testDevice(device) {
            const result = await this.request(`/api/devices/${device.id}/connectivity-test`, { method: "POST" });
            window.alert(result.message || (result.success ? "设备连接正常" : "设备连接失败"));
        },
        async deleteDevice(device) {
            if (!confirm(`确认删除设备 ${device.meter_id}？相关读数、告警和工单也会被清理。`)) return;
            await this.request(`/api/devices/${device.id}`, { method: "DELETE" });
            await this.loadPage();
        },
        userPayload() {
            const payload = { ...this.forms.user };
            if (!payload.password) delete payload.password;
            return payload;
        },
        async saveUser() {
            const payload = this.userPayload();
            const id = payload.id;
            delete payload.id;
            await this.request(id ? `/api/users/${id}` : "/api/users", {
                method: id ? "PUT" : "POST",
                body: JSON.stringify(payload),
            });
            this.resetUserForm();
            await this.loadPage();
        },
        editUser(user) {
            this.forms.user = {
                id: user.id,
                username: user.username,
                full_name: user.full_name,
                password: "",
                role: user.role,
                is_active: user.is_active,
                employee_no: user.employee_no || "",
                phone: user.phone || "",
                region: user.engineer_region || "",
                address: user.engineer_address || "",
            };
        },
        resetUserForm() {
            this.forms.user = userFormDefaults();
        },
        async deleteUser(user) {
            if (!confirm(`确认删除用户 ${user.username}？`)) return;
            await this.request(`/api/users/${user.id}`, { method: "DELETE" });
            await this.loadPage();
        },
        editWorkOrder(order) {
            this.forms.workOrder = {
                id: order.id,
                title: order.title,
                description: order.description,
                region: order.region || "",
                priority: order.priority || "medium",
                status: order.status || "pending",
                device_id: order.device_id || "",
                engineer_id: order.engineer_id || "",
            };
        },
        resetWorkOrderForm() {
            this.forms.workOrder = workOrderDefaults();
        },
        async saveWorkOrder() {
            const payload = { ...this.forms.workOrder };
            const id = payload.id;
            delete payload.id;
            await this.request(id ? `/api/work-orders/${id}` : "/api/work-orders", {
                method: id ? "PUT" : "POST",
                body: JSON.stringify(payload),
            });
            this.resetWorkOrderForm();
            await this.loadPage();
        },
        async deleteWorkOrder(order) {
            if (!confirm(`确认删除工单 ${order.title}？`)) return;
            await this.request(`/api/work-orders/${order.id}`, { method: "DELETE" });
            await this.loadPage();
        },
        async acceptOrder(order) {
            await this.request(`/api/work-orders/${order.id}/accept`, { method: "POST" });
            await this.loadPage();
        },
        async completeOrder(order) {
            const note = prompt("请输入现场处置结果：", "现场核查完成，已完成处置");
            if (note === null) return;
            await this.request(`/api/work-orders/${order.id}/complete`, {
                method: "POST",
                body: JSON.stringify({ completion_note: note }),
            });
            await this.loadPage();
        },
        async markAlert(alert, label) {
            await this.request(`/api/alerts/${alert.id}/feedback`, {
                method: "POST",
                body: JSON.stringify({ confirmed_label: label }),
            });
            await this.loadPage();
        },
        async loadHistory() {
            const suffix = this.filters.meterId ? `?meter_id=${encodeURIComponent(this.filters.meterId)}` : "";
            this.state.history = await this.request(`/api/history${suffix}`);
            this.state.reconstruction = await this.request(`/api/reconstruction${suffix}`);
            await nextTick();
            this.stabilizeVisuals(() => this.renderHistoryCharts());
        },
        async controlModule(target, action) {
            const payload = await this.request(`/api/${target}`, {
                method: "POST",
                body: JSON.stringify({ action }),
            });
            if (target === "training") this.state.training = payload.status;
            if (target === "simulator") this.state.simulator = payload;
            if (target === "mqtt") this.state.mqtt = payload.status;
            if (target === "drift") this.state.drift = payload.status;
            this.state.settings = await this.request("/api/settings");
        },
        chart(id) {
            const node = document.getElementById(id);
            if (!node || !window.echarts) return null;
            this.charts[id] = this.charts[id] || echarts.init(node);
            return this.charts[id];
        },
        stabilizeVisuals(callback) {
            nextTick(() => {
                const run = () => {
                    callback();
                    this.resizeVisuals();
                    setTimeout(() => this.resizeVisuals(), 180);
                };
                if (window.requestAnimationFrame) requestAnimationFrame(run);
                else setTimeout(run, 0);
            });
        },
        baseChartOption() {
            return {
                textStyle: { color: "#253241", fontFamily: "Inter, Microsoft YaHei, sans-serif" },
                tooltip: { trigger: "axis", borderWidth: 0, backgroundColor: "rgba(15,23,42,.92)", textStyle: { color: "#fff" } },
                grid: { left: 42, right: 18, top: 40, bottom: 42 },
                xAxis: { axisLine: { lineStyle: { color: "#d8e1eb" } }, axisTick: { show: false }, axisLabel: { color: "#64748b" } },
                yAxis: { splitLine: { lineStyle: { color: "#edf2f7" } }, axisLabel: { color: "#64748b" } },
            };
        },
        renderDashboardVisuals() {
            const cards = this.state.dashboard?.device_cards || [];
            const flowChart = this.chart("deviceChart");
            if (flowChart) {
                const base = this.baseChartOption();
                const top = cards.slice(0, 12);
                flowChart.setOption({
                    ...base,
                    xAxis: { ...base.xAxis, type: "category", data: top.map((item) => item.meter_id), axisLabel: { color: "#64748b", rotate: 28 } },
                    yAxis: { ...base.yAxis, type: "value", name: "m3/h" },
                    series: [{ type: "bar", name: "瞬时流量", data: top.map((item) => item.instant_flow || 0), barWidth: 18, itemStyle: { color: "#0f766e", borderRadius: [6, 6, 0, 0] } }],
                });
                flowChart.resize();
            }
            const trendChart = this.chart("trendChart");
            if (trendChart) {
                const base = this.baseChartOption();
                const rows = this.state.dashboard?.trend || [];
                trendChart.setOption({
                    ...base,
                    xAxis: { ...base.xAxis, type: "category", data: rows.map((item) => item.label) },
                    yAxis: { ...base.yAxis, type: "value" },
                    series: [{ type: "line", smooth: true, name: "告警数", data: rows.map((item) => item.anomaly_count || 0), areaStyle: { color: chartGradient("rgba(37,99,235,.28)") }, lineStyle: { width: 3, color: "#2563eb" }, itemStyle: { color: "#2563eb" } }],
                });
                trendChart.resize();
            }
            this.renderMap();
        },
        renderMap() {
            const node = document.getElementById("deviceMap");
            const points = this.state.dashboard?.map_points || [];
            if (!node) return;
            if (!window.L) {
                this.renderFallbackMap(node, points);
                return;
            }
            node.classList.remove("map-native");
            if (!this.map) {
                node.innerHTML = "";
                this.mapTileErrors = 0;
                this.map = L.map(node, { zoomControl: false, attributionControl: true }).setView(MAP_CENTER, 12);
                L.control.zoom({ position: "bottomright" }).addTo(this.map);
                this.mapTileLayer = L.tileLayer(AMAP_TILE_URL, {
                    maxZoom: 18,
                    minZoom: 3,
                    subdomains: AMAP_TILE_SUBDOMAINS,
                    attribution: "AMap",
                });
                this.mapTileLayer.on("tileerror", () => {
                    this.mapTileErrors += 1;
                    node.classList.add("map-fallback");
                    if (this.mapTileErrors >= MAP_TILE_ERROR_LIMIT) {
                        this.destroyLeafletMap(node);
                        this.renderFallbackMap(node, points);
                    }
                });
                this.mapTileLayer.on("load", () => {
                    this.mapTileErrors = 0;
                    node.classList.remove("map-fallback");
                });
                this.mapTileLayer.addTo(this.map);
            }
            if (this.mapLayer) this.map.removeLayer(this.mapLayer);
            this.mapLayer = L.layerGroup().addTo(this.map);
            const bounds = [];
            points.forEach((point) => {
                const coord = mapPointCoordinate(point);
                if (!coord) return;
                const [lat, lng] = coord;
                bounds.push([lat, lng]);
                const color = point.anomaly ? "#dc2626" : point.status === "online" ? "#059669" : "#64748b";
                L.circleMarker([lat, lng], {
                    radius: point.anomaly ? 9 : 7,
                    color: "#fff",
                    weight: 2,
                    fillColor: color,
                    fillOpacity: 0.92,
                }).bindPopup(`<strong>${point.meter_id}</strong><br>${point.name || ""}<br>${point.location || ""}`).addTo(this.mapLayer);
            });
            if (bounds.length) {
                this.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
            } else {
                this.map.setView(MAP_CENTER, 11);
            }
            setTimeout(() => this.map?.invalidateSize(), 80);
        },
        destroyLeafletMap(node) {
            if (this.map) this.map.remove();
            this.map = null;
            this.mapLayer = null;
            this.mapTileLayer = null;
            this.mapTileErrors = 0;
            if (node) node.innerHTML = "";
        },
        renderFallbackMap(node, points) {
            if (this.map) this.destroyLeafletMap(node);
            node.classList.add("map-fallback", "map-native");
            node.innerHTML = "";
            const validPoints = points
                .map((point) => {
                    const coord = mapPointCoordinate(point);
                    if (!coord) return null;
                    return { ...point, lat: coord[0], lng: coord[1] };
                })
                .filter(Boolean);
            const lats = validPoints.map((point) => point.lat);
            const lngs = validPoints.map((point) => point.lng);
            const minLat = Math.min(...lats, MAP_CENTER[0] - 0.05);
            const maxLat = Math.max(...lats, MAP_CENTER[0] + 0.05);
            const minLng = Math.min(...lngs, MAP_CENTER[1] - 0.08);
            const maxLng = Math.max(...lngs, MAP_CENTER[1] + 0.08);
            const layer = document.createElement("div");
            layer.className = "native-map-layer";
            layer.innerHTML = '<div class="native-map-title">设备地理态势</div><div class="native-map-subtitle">离线底图模式 · 设备坐标仍可展示</div>';
            const renderPoints = validPoints.length ? validPoints : [{ meter_id: "中心区域", name: "暂无设备坐标", location: "等待设备上报", status: "offline", anomaly: false, lat: 31.2304, lng: 121.4737 }];
            renderPoints.forEach((point) => {
                const marker = document.createElement("div");
                marker.className = `native-map-marker ${point.anomaly ? "danger" : point.status === "online" ? "online" : "offline"}`;
                const x = ((point.lng - minLng) / Math.max(maxLng - minLng, 0.001)) * 78 + 11;
                const y = (1 - (point.lat - minLat) / Math.max(maxLat - minLat, 0.001)) * 68 + 16;
                marker.style.left = `${Math.max(8, Math.min(92, x))}%`;
                marker.style.top = `${Math.max(12, Math.min(88, y))}%`;
                marker.title = `${point.meter_id || "-"} ${point.name || ""} ${point.location || ""}`;
                marker.innerHTML = `<span></span><strong>${point.meter_id || "-"}</strong>`;
                layer.appendChild(marker);
            });
            node.appendChild(layer);
        },
        renderHistoryCharts() {
            const rows = this.historyRows.slice(-80);
            const history = this.chart("historyChart");
            if (history) {
                const base = this.baseChartOption();
                history.setOption({
                    ...base,
                    legend: { top: 0, right: 0, data: ["瞬时流量", "管网压力", "电池电压"], textStyle: { color: "#64748b" } },
                    xAxis: { ...base.xAxis, type: "category", data: rows.map((item) => this.shortDate(item.timestamp)) },
                    yAxis: { ...base.yAxis, type: "value" },
                    series: [
                        { type: "line", name: "瞬时流量", smooth: true, data: rows.map((item) => item.instant_flow || 0), lineStyle: { color: "#0f766e" }, itemStyle: { color: "#0f766e" } },
                        { type: "line", name: "管网压力", smooth: true, data: rows.map((item) => item.pressure || 0), lineStyle: { color: "#2563eb" }, itemStyle: { color: "#2563eb" } },
                        { type: "line", name: "电池电压", smooth: true, data: rows.map((item) => item.battery_voltage || 0), lineStyle: { color: "#d97706" }, itemStyle: { color: "#d97706" } },
                    ],
                });
                history.resize();
            }
            const reconstruction = this.state.reconstruction || {};
            const trace = this.chart("reconstructionChart");
            if (trace) {
                const base = this.baseChartOption();
                const original = (reconstruction.original || []).map((item) => item.instant_flow ?? item);
                const rebuilt = (reconstruction.reconstructed || []).map((item) => item.instant_flow ?? item);
                const labels = (reconstruction.timestamps || original).map((_, index) => index + 1);
                trace.setOption({
                    ...base,
                    legend: { top: 0, right: 0, data: ["原始流量", "重构流量", "重构误差"], textStyle: { color: "#64748b" } },
                    xAxis: { ...base.xAxis, type: "category", data: labels },
                    yAxis: { ...base.yAxis, type: "value" },
                    series: [
                        { type: "line", name: "原始流量", smooth: true, data: original, lineStyle: { color: "#0f766e" }, itemStyle: { color: "#0f766e" } },
                        { type: "line", name: "重构流量", smooth: true, data: rebuilt, lineStyle: { color: "#2563eb" }, itemStyle: { color: "#2563eb" } },
                        { type: "bar", name: "重构误差", data: reconstruction.error_series || [], itemStyle: { color: "#dc2626", borderRadius: [4, 4, 0, 0] } },
                    ],
                });
                trace.resize();
            }
        },
        renderReportChart() {
            const report = this.state.reports || {};
            const chart = this.chart("reportChart");
            if (!chart) return;
            const orders = report.order_summary || {};
            const severity = report.severity_summary || {};
            chart.setOption({
                tooltip: { trigger: "item", borderWidth: 0, backgroundColor: "rgba(15,23,42,.92)", textStyle: { color: "#fff" } },
                legend: { bottom: 0, textStyle: { color: "#64748b" } },
                series: [
                    {
                        name: "工单状态",
                        type: "pie",
                        radius: ["46%", "68%"],
                        center: ["29%", "46%"],
                        data: [
                            { name: "未完成", value: orders.open_orders || 0, itemStyle: { color: "#2563eb" } },
                            { name: "已完成", value: orders.completed_orders || 0, itemStyle: { color: "#0f766e" } },
                        ],
                    },
                    {
                        name: "告警等级",
                        type: "pie",
                        radius: ["46%", "68%"],
                        center: ["72%", "46%"],
                        data: [
                            { name: "紧急", value: severity.high || 0, itemStyle: { color: "#dc2626" } },
                            { name: "重要", value: severity.medium || 0, itemStyle: { color: "#d97706" } },
                            { name: "一般", value: severity.low || 0, itemStyle: { color: "#64748b" } },
                        ],
                    },
                ],
            });
            chart.resize();
        },
    },
    template: `
    <main v-if="!user" class="login-shell">
        <section class="login-stage">
            <div class="login-copy">
                <p class="eyebrow">IoT anomaly intelligence</p>
                <h1>智能燃气表数据异常检测系统</h1>
                <p>面向燃气物联网的实时监测、异常识别、告警研判与工单闭环平台。</p>
            </div>
            <div class="tech-panel" aria-hidden="true">
                <div class="orbit orbit-a"></div>
                <div class="orbit orbit-b"></div>
                <div class="signal-core"><span>LSTM</span><strong>AE</strong></div>
                <div class="telemetry-card card-a"><span>Reconstruction error</span><strong>0.018</strong></div>
                <div class="telemetry-card card-b"><span>Device stream</span><strong>24h</strong></div>
                <div class="telemetry-card card-c"><span>Risk level</span><strong>Normal</strong></div>
            </div>
            <div class="login-metrics"><span>Vue 3</span><span>ECharts</span><span>Leaflet</span><span>WebSocket</span></div>
        </section>
        <form class="login-panel" @submit.prevent="login">
            <p class="eyebrow">Secure console</p>
            <h2>登录系统</h2>
            <label>用户名</label>
            <input v-model.trim="loginForm.username" autocomplete="username" required>
            <label>密码</label>
            <input v-model="loginForm.password" type="password" autocomplete="current-password" required>
            <button :disabled="busy">{{ busy ? '正在验证' : '进入控制台' }}</button>
            <p v-if="message" class="error-text">{{ message }}</p>
        </form>
    </main>

    <main v-else class="app-shell">
        <aside class="sidebar">
            <div class="brand"><span>GM</span><strong>燃气异常检测</strong></div>
            <nav>
                <button v-for="item in visiblePages" :key="item.key" :class="{active: page === item.key}" @click="go(item.key)">
                    <span>{{ item.label }}</span><small>{{ item.hint }}</small>
                </button>
            </nav>
        </aside>

        <section class="content">
            <header class="topbar">
                <div><p class="eyebrow">Smart Gas Monitoring</p><h1>{{ currentPage.label }}</h1></div>
                <div class="topbar-actions"><span class="live-dot" :class="{muted: realtimeText !== '实时在线'}">{{ realtimeText }}</span><span class="user-chip">{{ user.full_name }} · {{ roleLabel(user.role) }}</span><button class="ghost" @click="logout">退出</button></div>
            </header>

            <p v-if="message" class="error-text">{{ message }}</p>

            <section v-if="page === 'dashboard' && state.dashboard" class="dashboard-grid">
                <div class="stats-row">
                    <article class="stat"><span>在线设备</span><strong>{{ summary.connected_devices || 0 }}</strong><em>实时上报</em></article>
                    <article class="stat"><span>离线设备</span><strong>{{ summary.offline_devices || 0 }}</strong><em>需关注</em></article>
                    <article class="stat danger"><span>异常设备</span><strong>{{ summary.abnormal_devices || 0 }}</strong><em>模型判定</em></article>
                    <article class="stat"><span>待办工单</span><strong>{{ openOrders }}</strong><em>闭环处置</em></article>
                </div>
                <section class="panel map-panel"><div class="panel-title"><div><h2>设备地理分布</h2><p>{{ summary.total_devices || 0 }} 台设备 · 在线/离线/异常状态</p></div><button class="ghost" @click="loadPage">刷新</button></div><div id="deviceMap" class="map"></div></section>
                <section class="panel"><div class="panel-title"><div><h2>瞬时流量排行</h2><p>最近上报 Top 12</p></div></div><div id="deviceChart" class="chart"></div></section>
                <section class="panel"><div class="panel-title"><div><h2>告警趋势</h2><p>最近 24 小时</p></div></div><div id="trendChart" class="chart compact"></div></section>
                <section class="panel"><div class="panel-title"><div><h2>最新告警</h2><p>模型与规则融合研判</p></div><button class="ghost" @click="go('alerts')">全部</button></div><article v-for="alert in state.alerts.slice(0, 5)" :key="alert.id" class="record"><strong>{{ alert.meter_id }} · {{ severityLabel(alert.severity) }}</strong><span>{{ date(alert.created_at) }} · 得分 {{ number(alert.score) }}</span><p>{{ alert.anomaly_type || alert.description }}</p></article><div v-if="!state.alerts.length" class="empty">暂无告警</div></section>
            </section>

            <section v-if="page === 'devices'" class="panel">
                <div class="panel-title"><div><h2>设备管理</h2><p>设备接入、启停控制、连通性测试和最新读数</p></div><span>{{ state.devices.length }} 台</span></div>
                <div class="table-wrap"><table><thead><tr><th>设备</th><th>位置</th><th>状态</th><th>最新读数</th><th>通信</th><th>操作</th></tr></thead><tbody><tr v-for="device in state.devices" :key="device.id"><td><strong>{{ device.meter_id }}</strong><br><span>{{ device.name }}</span></td><td>{{ device.location }}<br><span>{{ device.area || '-' }}</span></td><td><span class="pill" :class="device.status">{{ statusLabel(device.status) }}</span><span class="pill">{{ device.is_enabled ? '启用' : '停用' }}</span></td><td>流量 {{ number(latest(device).instant_flow, 4) }} m3/h<br><span>电压 {{ number(latest(device).battery_voltage) }} V · 信号 {{ number(latest(device).signal_strength, 0) }}</span></td><td>{{ device.protocol }}<br><span>{{ date(device.last_seen_at) }}</span></td><td><button @click="toggleDevice(device)">{{ device.is_enabled ? '停用' : '启用' }}</button><button class="ghost" @click="testDevice(device)">测试</button><button v-if="canSuperAdmin" class="ghost danger-text" @click="deleteDevice(device)">删除</button></td></tr></tbody></table></div>
            </section>

            <section v-if="page === 'alerts'" class="split alerts-layout">
                <section class="panel"><div class="panel-title"><div><h2>异常告警中心</h2><p>支持人工反馈沉淀标注样本</p></div><select v-model="filters.alertSort" @change="loadPage"><option value="time">按时间</option><option value="severity">按紧急程度</option></select></div><article v-for="alert in state.alerts" :key="alert.id" class="record"><strong>{{ alert.meter_id }} · {{ severityLabel(alert.severity) }}</strong><span>{{ date(alert.created_at) }} · 得分 {{ number(alert.score) }} · 阈值 {{ number(alert.threshold) }} · {{ statusLabel(alert.status) }}</span><p>{{ alert.description || alert.anomaly_type }}</p><button v-if="canAdmin" @click="markAlert(alert, 'confirmed_anomaly')">确认异常</button><button v-if="canAdmin" class="ghost" @click="markAlert(alert, 'false_positive')">标记误报</button><button v-if="canAdmin" class="ghost" @click="markAlert(alert, 'ignored')">忽略</button></article><div v-if="!state.alerts.length" class="empty">暂无告警</div></section>
                <section v-if="canAdmin" class="panel"><div class="panel-title"><div><h2>反馈样本</h2><p>用于持续训练与阈值校准</p></div><span>{{ state.labeledSamples.length }} 条</span></div><article v-for="sample in state.labeledSamples.slice(0, 12)" :key="sample.id" class="record compact-record"><strong>{{ sample.meter_id }} · {{ sampleLabel(sample.confirmed_label) }}</strong><span>{{ date(sample.handled_at || sample.created_at) }}</span></article><div v-if="!state.labeledSamples.length" class="empty">暂无反馈样本</div></section>
            </section>

            <section v-if="page === 'work_orders'" class="split">
                <form v-if="canAdmin" class="panel form-panel" @submit.prevent="saveWorkOrder"><div class="panel-title"><div><h2>工单编辑</h2><p>按片区自动候选派单</p></div><button type="button" class="ghost" @click="resetWorkOrderForm">清空</button></div><input v-model.trim="forms.workOrder.title" placeholder="工单标题" required><textarea v-model.trim="forms.workOrder.description" placeholder="问题描述" required></textarea><div class="form-grid"><input v-model.trim="forms.workOrder.region" placeholder="负责片区" required><select v-model="forms.workOrder.priority"><option value="high">高优先级</option><option value="medium">中优先级</option><option value="low">低优先级</option></select></div><select v-model="forms.workOrder.status"><option value="pending">待处理</option><option value="assigned">已派单</option><option value="in_progress">处理中</option><option value="completed">已完成</option></select><select v-model="forms.workOrder.device_id" required><option value="">选择设备</option><option v-for="device in state.devices" :key="device.id" :value="device.id">{{ device.meter_id }} · {{ device.location }}</option></select><select v-model="forms.workOrder.engineer_id"><option value="">自动/暂不分配</option><option v-for="engineer in state.engineers" :key="engineer.id" :value="engineer.id">{{ engineer.name }} · {{ engineer.region }} · {{ engineer.active_orders }} 单</option></select><button>保存工单</button></form>
                <section class="panel"><div class="panel-title"><div><h2>工单列表</h2><p>从告警到处置结果回写</p></div><span>{{ filteredWorkOrders.length }} 条</span></div><article v-for="order in filteredWorkOrders" :key="order.id" class="record"><strong>{{ order.title }} · {{ priorityLabel(order.priority) }}</strong><span>{{ statusLabel(order.status) }} · {{ order.meter_id }} · {{ order.engineer_name || '未分配' }}</span><p>{{ order.description }}</p><div class="flow"><span v-for="node in order.flow_nodes" :key="node.stage" :class="{active: node.active, current: node.current}">{{ node.label }}</span></div><button v-if="canAdmin" @click="editWorkOrder(order)">编辑</button><button v-if="canAdmin" class="ghost danger-text" @click="deleteWorkOrder(order)">删除</button><button v-if="isEngineer && order.status === 'assigned'" @click="acceptOrder(order)">接单</button><button v-if="isEngineer && order.status === 'in_progress'" @click="completeOrder(order)">完成</button></article><div v-if="!filteredWorkOrders.length" class="empty">暂无工单</div></section>
            </section>

            <section v-if="page === 'engineers'" class="panel"><div class="panel-title"><div><h2>工程师状态</h2><p>工程师账号自动生成档案，展示在线状态与当前负载</p></div><span>{{ state.engineers.length }} 人</span></div><div class="card-grid"><article v-for="engineer in state.engineers" :key="engineer.id" class="mini-card"><strong>{{ engineer.name }}</strong><span>{{ engineer.employee_no }} · {{ engineer.region }}</span><p>{{ engineer.is_online ? '在线' : '离线' }} · 当前工单 {{ engineer.active_orders }}</p><p>{{ engineer.phone }} · {{ engineer.address }}</p></article></div><div v-if="!state.engineers.length" class="empty">暂无工程师档案，请在用户权限中创建工程师账号。</div></section>

            <section v-if="page === 'history'" class="panel"><div class="panel-title"><div><h2>历史数据与重构分析</h2><p>对比原始流量、重构流量和重构误差</p></div><select v-model="filters.meterId" @change="loadHistory"><option value="">全部设备</option><option v-for="device in state.devices" :key="device.id" :value="device.meter_id">{{ device.meter_id }}</option></select></div><div class="charts-2"><div id="historyChart" class="chart"></div><div id="reconstructionChart" class="chart"></div></div><div v-if="state.reconstruction && !state.reconstruction.ready" class="empty">{{ state.reconstruction.message || '重构分析需要更多连续读数。' }}</div><div class="table-wrap compact-table"><table><thead><tr><th>设备</th><th>时间</th><th>流量</th><th>压力</th><th>电压</th><th>异常得分</th><th>模型</th></tr></thead><tbody><tr v-for="row in historyRows.slice(-24).reverse()" :key="row.meter_id + row.timestamp"><td>{{ row.meter_id }}</td><td>{{ date(row.timestamp) }}</td><td>{{ number(row.instant_flow, 4) }}</td><td>{{ number(row.pressure) }}</td><td>{{ number(row.battery_voltage) }}</td><td>{{ number(row.anomaly_score) }}</td><td>{{ row.model_version || '-' }}</td></tr></tbody></table></div></section>

            <section v-if="page === 'reports'" class="panel"><div class="panel-title"><div><h2>统计报表</h2><p>告警等级和工单闭环效率概览</p></div></div><div class="report-summary"><article><span>工单总数</span><strong>{{ state.reports?.order_summary?.total_orders || 0 }}</strong></article><article><span>未完成</span><strong>{{ state.reports?.order_summary?.open_orders || 0 }}</strong></article><article><span>已完成</span><strong>{{ state.reports?.order_summary?.completed_orders || 0 }}</strong></article><article><span>紧急告警</span><strong>{{ state.reports?.severity_summary?.high || 0 }}</strong></article></div><div id="reportChart" class="chart large"></div></section>

            <section v-if="page === 'settings'" class="settings-grid">
                <section class="panel modules-panel"><div class="panel-title"><div><h2>模块控制</h2><p>仿真接入、持续训练、MQTT 网关与漂移监控</p></div></div><div class="card-grid"><article class="mini-card"><strong>虚拟设备模拟器</strong><span>{{ moduleRunning(state.simulator) ? '运行中' : '已停止' }}</span><button @click="controlModule('simulator', moduleRunning(state.simulator) ? 'stop' : 'start')">{{ moduleRunning(state.simulator) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>持续训练流水线</strong><span>{{ moduleRunning(state.training) ? '运行中' : '已停止' }}</span><button @click="controlModule('training', moduleRunning(state.training) ? 'stop' : 'start')">{{ moduleRunning(state.training) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>MQTT 网关</strong><span>{{ moduleRunning(state.mqtt) ? '运行中' : '已停止' }}</span><button @click="controlModule('mqtt', moduleRunning(state.mqtt) ? 'stop' : 'start')">{{ moduleRunning(state.mqtt) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>数据漂移监控</strong><span>{{ moduleRunning(state.drift) ? '运行中' : '已停止' }}</span><button @click="controlModule('drift', moduleRunning(state.drift) ? 'stop' : 'start')">{{ moduleRunning(state.drift) ? '停止' : '启动' }}</button><button class="ghost" @click="controlModule('drift', 'check')">立即检查</button></article></div></section>
                <section class="panel"><div class="panel-title"><div><h2>系统状态</h2><p>数据与模型运行概览</p></div></div><div class="kv"><span>用户数</span><strong>{{ state.settings?.user_count }}</strong><span>物理数据</span><strong>{{ state.settings?.physical_data_count }}</strong><span>训练原始数据</span><strong>{{ state.settings?.training_raw_data_count }}</strong><span>清洗数据</span><strong>{{ state.settings?.training_clean_data_count }}</strong><span>激活模型</span><strong>{{ activeModel }}</strong><span>F1</span><strong>{{ number(state.settings?.active_model_f1) }}</strong></div></section>
                <section class="panel wide-settings"><div class="panel-title"><div><h2>模型版本</h2><p>LSTM AutoEncoder 注册表最近版本</p></div><span>最近 10 个</span></div><div class="table-wrap"><table><thead><tr><th>模型</th><th>创建时间</th><th>阈值</th><th>准确率</th><th>Precision</th><th>Recall</th><th>F1</th><th>状态</th></tr></thead><tbody><tr v-for="model in state.settings?.model_versions || []" :key="model.model_id"><td>{{ model.model_id }}</td><td>{{ date(model.created_at) }}</td><td>{{ number(model.threshold, 4) }}</td><td>{{ number(model.accuracy) }}</td><td>{{ number(model.precision) }}</td><td>{{ number(model.recall) }}</td><td>{{ number(model.f1) }}</td><td>{{ model.is_active ? '当前' : '候选' }}</td></tr></tbody></table></div></section>
            </section>

            <section v-if="page === 'users'" class="split">
                <form class="panel form-panel" @submit.prevent="saveUser"><div class="panel-title"><div><h2>用户编辑</h2><p>管理员与工程师账号分权</p></div><button type="button" class="ghost" @click="resetUserForm">清空</button></div><input v-model.trim="forms.user.username" placeholder="用户名" required><input v-model.trim="forms.user.full_name" placeholder="姓名" required><input v-model="forms.user.password" type="password" placeholder="密码，新建必填，编辑可留空"><div class="form-grid"><select v-model="forms.user.role"><option value="sub_admin">管理员</option><option value="engineer">工程师</option></select><select v-model="forms.user.is_active"><option :value="true">启用</option><option :value="false">停用</option></select></div><div class="form-grid"><input v-model.trim="forms.user.employee_no" placeholder="工号" required><input v-model.trim="forms.user.phone" placeholder="电话" required></div><template v-if="forms.user.role === 'engineer'"><input v-model.trim="forms.user.region" placeholder="负责片区" required><input v-model.trim="forms.user.address" placeholder="地址" required></template><button>保存用户</button></form>
                <section class="panel"><div class="panel-title"><div><h2>用户列表</h2><p>按角色控制页面和操作权限</p></div><span>{{ state.users.length }} 个账号</span></div><article v-for="item in state.users" :key="item.id" class="record"><strong>{{ item.full_name }}</strong><span>{{ item.username }} · {{ roleLabel(item.role) }} · {{ item.is_active ? '启用' : '停用' }}</span><button @click="editUser(item)">编辑</button><button v-if="item.role !== 'super_admin'" class="ghost danger-text" @click="deleteUser(item)">删除</button></article></section>
            </section>
        </section>
    </main>
    `,
}).mount("#app");
