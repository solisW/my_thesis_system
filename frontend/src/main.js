try {
const { createApp, nextTick } = Vue;
const { API_BASE, AMAP_TILE_URL, AMAP_TILE_SUBDOMAINS, MAP_CENTER, MAP_TILE_ERROR_LIMIT } = window.AppConfig || {};
const { emptyState, userFormDefaults, workOrderDefaults, numberText, dateText, shortDateText } = window.AppFormatters || {};
const { mapPointCoordinate } = window.MapUtils || {};
if (!window.Vue || !window.echarts || !window.AppConfig || !window.AppPages || !window.ApiClient || !window.AppFormatters || !window.MapUtils) {
    throw new Error("前端依赖未完整加载，请检查 frontend/vendor 和 frontend/src 资源。");
}
const pageMeta = window.AppPages;
const api = new window.ApiClient(API_BASE);

const appInstance = createApp({
    data() {
        return {
            apiBase: API_BASE,
            user: null,
            page: location.hash.replace("#/", "") || "dashboard",
            loginForm: { username: "", password: "" },
            message: "",
            busy: false,
            pageLoading: false,
            realtimeText: "连接中",
            state: emptyState(),
            filters: { alertSort: "time", meterId: "", mapStatus: "all" },
            forms: { user: userFormDefaults(), workOrder: workOrderDefaults() },
            socket: null,
            charts: {},
            map: null,
            mapLayer: null,
            mapTileLayer: null,
            mapTileErrors: 0,
            mapTileLoadTimer: null,
            mapFallbackTimer: null,
            visualRefreshTimer: null,
            visualResizeObserver: null,
            loadRequestId: 0,
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
        dashboardCards() {
            return this.state.dashboard?.device_cards || [];
        },
        dashboardTrend() {
            return this.state.dashboard?.trend || [];
        },
        filteredMapPoints() {
            const points = this.state.dashboard?.map_points || [];
            if (this.filters.mapStatus === "online") return points.filter((point) => point.status === "online");
            if (this.filters.mapStatus === "offline") return points.filter((point) => point.status !== "online");
            if (this.filters.mapStatus === "anomaly") return points.filter((point) => point.anomaly);
            return points;
        },
        mapFilterCounts() {
            const points = this.state.dashboard?.map_points || [];
            return {
                all: points.length,
                online: points.filter((point) => point.status === "online").length,
                offline: points.filter((point) => point.status !== "online").length,
                anomaly: points.filter((point) => point.anomaly).length,
            };
        },
        recentHistoryRows() {
            return this.historyRows.slice(-80);
        },
        reconstructionSeries() {
            const reconstruction = this.state.reconstruction || {};
            const original = (reconstruction.original || []).map((item) => item.instant_flow ?? item);
            const rebuilt = (reconstruction.reconstructed || []).map((item) => item.instant_flow ?? item);
            const errors = reconstruction.error_series || [];
            const labelSource = reconstruction.timestamps || (original.length ? original : rebuilt);
            return {
                labels: labelSource.map((_, index) => index + 1),
                original,
                rebuilt,
                errors,
                emptyText: reconstruction.message || "暂无重构曲线数据",
            };
        },
        reportPieGroups() {
            const report = this.state.reports || {};
            const orders = report.order_summary || {};
            const severity = report.severity_summary || {};
            return [
                {
                    title: "工单状态",
                    emptyText: "暂无工单",
                    items: [
                        { name: "未完成", value: orders.open_orders || 0, color: "#2563eb" },
                        { name: "已完成", value: orders.completed_orders || 0, color: "#0f766e" },
                    ],
                },
                {
                    title: "告警等级",
                    emptyText: "暂无告警",
                    items: [
                        { name: "紧急", value: severity.high || 0, color: "#dc2626" },
                        { name: "重要", value: severity.medium || 0, color: "#d97706" },
                        { name: "一般", value: severity.low || 0, color: "#64748b" },
                    ],
                },
            ];
        },
        dashboardFlowChartHtml() {
            return this.nativeBarChartHtml(this.dashboardCards.slice(0, 12), {
                labelKey: "meter_id",
                valueKey: "instant_flow",
                emptyText: "暂无设备流量数据",
                title: "瞬时流量排行",
                color: "#0f766e",
            });
        },
        dashboardTrendChartHtml() {
            return this.nativeLineChartHtml(
                this.dashboardTrend.map((item) => item.label),
                [{ name: "告警数", values: this.dashboardTrend.map((item) => item.anomaly_count || 0), color: "#2563eb" }],
                { emptyText: "暂无告警趋势数据", title: "告警趋势" },
            );
        },
        historyChartHtml() {
            return this.nativeLineChartHtml(
                this.recentHistoryRows.map((item) => this.shortDate(item.timestamp)),
                [
                    { name: "瞬时流量", values: this.recentHistoryRows.map((item) => item.instant_flow || 0), color: "#0f766e" },
                    { name: "管网压力", values: this.recentHistoryRows.map((item) => item.pressure || 0), color: "#2563eb" },
                    { name: "电池电压", values: this.recentHistoryRows.map((item) => item.battery_voltage || 0), color: "#d97706" },
                ],
                { emptyText: "暂无历史读数数据", title: "历史数据曲线" },
            );
        },
        reconstructionChartHtml() {
            return this.nativeLineChartHtml(
                this.reconstructionSeries.labels,
                [
                    { name: "原始流量", values: this.reconstructionSeries.original, color: "#0f766e" },
                    { name: "重构流量", values: this.reconstructionSeries.rebuilt, color: "#2563eb" },
                    { name: "重构误差", values: this.reconstructionSeries.errors, color: "#dc2626" },
                ],
                { emptyText: this.reconstructionSeries.emptyText, title: "重构分析曲线" },
            );
        },
        reportChartHtml() {
            return this.nativePiesHtml(this.reportPieGroups);
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
        if (this.visualRefreshTimer) clearTimeout(this.visualRefreshTimer);
        if (this.visualResizeObserver) this.visualResizeObserver.disconnect();
        this.cleanupVisuals();
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
            return api.request(path, options);
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
            const nextPage = location.hash.replace("#/", "") || "dashboard";
            if (this.page !== nextPage) this.cleanupVisuals();
            this.page = nextPage;
            this.ensureAllowedPage();
            this.loadPage();
        },
        go(page) {
            location.hash = `#/${page}`;
        },
        cleanupVisuals() {
            if (this.visualResizeObserver) {
                this.visualResizeObserver.disconnect();
                this.visualResizeObserver = null;
            }
            this.disposeCharts();
            this.destroyLeafletMap();
        },
        async loadPage() {
            if (!this.user) return;
            this.disposeCharts();
            const requestId = ++this.loadRequestId;
            const page = this.page;
            this.pageLoading = true;
            this.message = "";
            try {
                if (page === "dashboard") {
                    const [dashboard, workOrders] = await Promise.all([
                        this.request("/api/dashboard"),
                        this.request("/api/work-orders"),
                    ]);
                    if (requestId !== this.loadRequestId) return;
                    this.state.dashboard = dashboard;
                    this.state.alerts = this.state.dashboard.alerts || [];
                    this.state.workOrders = workOrders;
                    this.requestVisualRefresh();
                }
                if (page === "devices") {
                    const devices = await this.request("/api/devices");
                    if (requestId !== this.loadRequestId) return;
                    this.state.devices = devices;
                }
                if (page === "alerts") {
                    const [alerts, labeledSamples] = await Promise.all([
                        this.request(`/api/alerts?limit=50&sort_by=${encodeURIComponent(this.filters.alertSort)}`),
                        this.canAdmin ? this.request("/api/labeled-samples") : Promise.resolve(this.state.labeledSamples),
                    ]);
                    if (requestId !== this.loadRequestId) return;
                    this.state.alerts = alerts;
                    if (this.canAdmin) this.state.labeledSamples = labeledSamples;
                }
                if (page === "work_orders") {
                    const [devices, engineers, workOrders] = await Promise.all([
                        this.canAdmin ? this.request("/api/devices") : Promise.resolve(this.state.devices),
                        this.canAdmin ? this.request("/api/engineers") : Promise.resolve(this.state.engineers),
                        this.request("/api/work-orders"),
                    ]);
                    if (requestId !== this.loadRequestId) return;
                    if (this.canAdmin) {
                        this.state.devices = devices;
                        this.state.engineers = engineers;
                    }
                    this.state.workOrders = workOrders;
                }
                if (page === "engineers") {
                    const engineers = await this.request("/api/engineers");
                    if (requestId !== this.loadRequestId) return;
                    this.state.engineers = engineers;
                }
                if (page === "users") {
                    const [users, engineers] = await Promise.all([
                        this.request("/api/users"),
                        this.request("/api/engineers"),
                    ]);
                    if (requestId !== this.loadRequestId) return;
                    this.state.users = users;
                    this.state.engineers = engineers;
                }
                if (page === "history") {
                    const devices = await this.request("/api/devices");
                    if (requestId !== this.loadRequestId) return;
                    this.state.devices = devices;
                    await this.loadHistory(requestId);
                }
                if (page === "reports") {
                    const reports = await this.request("/api/reports");
                    if (requestId !== this.loadRequestId) return;
                    this.state.reports = reports;
                    this.requestVisualRefresh();
                }
                if (page === "settings") {
                    const [settings, training, simulator, mqtt, drift] = await Promise.all([
                        this.request("/api/settings"),
                        this.request("/api/training"),
                        this.request("/api/simulator"),
                        this.request("/api/mqtt"),
                        this.request("/api/drift"),
                    ]);
                    if (requestId !== this.loadRequestId) return;
                    this.state.settings = settings;
                    this.state.training = training.status;
                    this.state.simulator = simulator;
                    this.state.mqtt = mqtt.status;
                    this.state.drift = drift.status;
                }
            } catch (error) {
                if (requestId === this.loadRequestId) this.message = error.message;
            } finally {
                if (requestId === this.loadRequestId) {
                    this.pageLoading = false;
                    this.requestVisualRefresh();
                }
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
            if (eventName === "map" && this.state.dashboard) this.state.dashboard.map_points = payload || [];
            this.requestVisualRefresh();
        },
        resizeVisuals() {
            this.invalidateVisualSizes();
            this.requestVisualRefresh(120);
        },
        latest(device) {
            return device?.latest_reading || {};
        },
        number(value, digits = 2) {
            return numberText(value, digits);
        },
        date(value) {
            return dateText(value);
        },
        shortDate(value) {
            return shortDateText(value);
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
        async loadHistory(requestId = this.loadRequestId) {
            if (typeof requestId !== "number") requestId = this.loadRequestId;
            const suffix = this.filters.meterId ? `?meter_id=${encodeURIComponent(this.filters.meterId)}` : "";
            const [history, reconstruction] = await Promise.all([
                this.request(`/api/history${suffix}`),
                this.request(`/api/reconstruction${suffix}`),
            ]);
            if (requestId !== this.loadRequestId) return;
            this.state.history = history;
            this.state.reconstruction = reconstruction;
            this.requestVisualRefresh();
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
        escapeHtml(value) {
            return String(value ?? "").replace(/[&<>"']/g, (char) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            }[char]));
        },
        polarPoint(cx, cy, r, angle) {
            return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
        },
        donutSegment(cx, cy, outerR, innerR, start, end, color, label) {
            if (end - start >= Math.PI * 2) end = start + Math.PI * 2 - 0.001;
            const large = end - start > Math.PI ? 1 : 0;
            const [x1, y1] = this.polarPoint(cx, cy, outerR, start);
            const [x2, y2] = this.polarPoint(cx, cy, outerR, end);
            const [x3, y3] = this.polarPoint(cx, cy, innerR, end);
            const [x4, y4] = this.polarPoint(cx, cy, innerR, start);
            return `<path d="M ${x1} ${y1} A ${outerR} ${outerR} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerR} ${innerR} 0 ${large} 0 ${x4} ${y4} Z" fill="${color}"><title>${this.escapeHtml(label)}</title></path>`;
        },
        nativeBarChartHtml(rows, options = {}) {
            const data = (rows || [])
                .map((item) => ({
                    label: item[options.labelKey || "label"] ?? "-",
                    value: Number(item[options.valueKey || "value"] || 0),
                }))
                .filter((item) => Number.isFinite(item.value));
            if (!data.length) return `<div class="native-chart-layer"><div class="native-chart-empty">${this.escapeHtml(options.emptyText || "暂无数据")}</div></div>`;
            const width = 760;
            const height = 250;
            const pad = { left: 42, right: 18, top: 16, bottom: 54 };
            const max = Math.max(...data.map((item) => item.value), 1);
            const plotW = width - pad.left - pad.right;
            const plotH = height - pad.top - pad.bottom;
            const gap = 10;
            const barW = Math.max(12, (plotW - gap * (data.length - 1)) / data.length);
            const bars = data.map((item, index) => {
                const h = Math.max(3, item.value / max * plotH);
                const x = pad.left + index * (barW + gap);
                const y = pad.top + plotH - h;
                const label = this.escapeHtml(item.label);
                return `
                    <g>
                        <rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="5" fill="${options.color || "#0f766e"}"></rect>
                        <text x="${x + barW / 2}" y="${height - 22}" text-anchor="end" transform="rotate(-28 ${x + barW / 2} ${height - 22})">${label}</text>
                        <title>${label}: ${item.value.toFixed(4)}</title>
                    </g>`;
            }).join("");
            return `
                <div class="native-chart-layer">
                    <svg class="native-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${this.escapeHtml(options.title || "柱状图")}">
                        <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotH}" stroke="#d8e1eb"></line>
                        <line x1="${pad.left}" y1="${pad.top + plotH}" x2="${width - pad.right}" y2="${pad.top + plotH}" stroke="#d8e1eb"></line>
                        <g class="native-chart-grid">
                            <line x1="${pad.left}" y1="${pad.top + plotH * .33}" x2="${width - pad.right}" y2="${pad.top + plotH * .33}"></line>
                            <line x1="${pad.left}" y1="${pad.top + plotH * .66}" x2="${width - pad.right}" y2="${pad.top + plotH * .66}"></line>
                        </g>
                        <g class="native-chart-bars">${bars}</g>
                    </svg>
                </div>`;
        },
        nativeLineChartHtml(labels, series, options = {}) {
            const cleanSeries = (series || []).map((item) => ({
                ...item,
                values: (item.values || []).map((value) => Number(value || 0)).filter((value) => Number.isFinite(value)),
            }));
            const hasData = cleanSeries.some((item) => item.values.length);
            if (!hasData) return `<div class="native-chart-layer"><div class="native-chart-empty">${this.escapeHtml(options.emptyText || "暂无数据")}</div></div>`;
            const width = 760;
            const height = 250;
            const pad = { left: 42, right: 18, top: 24, bottom: 42 };
            const allValues = cleanSeries.flatMap((item) => item.values);
            const max = Math.max(...allValues, 1);
            const min = Math.min(...allValues, 0);
            const span = Math.max(max - min, 1);
            const maxLen = Math.max(...cleanSeries.map((item) => item.values.length), labels.length, 2);
            const x = (index) => pad.left + index / Math.max(maxLen - 1, 1) * (width - pad.left - pad.right);
            const y = (value) => pad.top + (1 - (value - min) / span) * (height - pad.top - pad.bottom);
            const paths = cleanSeries.map((item) => {
                const points = item.values.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`);
                if (!points.length) return "";
                const circles = item.values.map((value, index) => `<circle cx="${x(index)}" cy="${y(value)}" r="3"><title>${this.escapeHtml(item.name)}: ${value}</title></circle>`).join("");
                return `<g style="--series-color:${item.color}"><polyline points="${points.join(" ")}"></polyline>${circles}</g>`;
            }).join("");
            const tickStep = Math.max(1, Math.ceil(maxLen / 6));
            const ticks = Array.from({ length: maxLen }, (_, index) => index)
                .filter((index) => index % tickStep === 0 || index === maxLen - 1)
                .map((index) => `<text x="${x(index)}" y="${height - 14}" text-anchor="middle">${this.escapeHtml(labels[index] ?? index + 1)}</text>`)
                .join("");
            const legend = cleanSeries.map((item) => `<span><i style="background:${item.color}"></i>${this.escapeHtml(item.name)}</span>`).join("");
            return `
                <div class="native-chart-layer">
                    <div class="native-chart-legend">${legend}</div>
                    <svg class="native-chart-svg has-legend" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${this.escapeHtml(options.title || "折线图")}">
                        <g class="native-chart-grid">
                            <line x1="${pad.left}" y1="${pad.top}" x2="${width - pad.right}" y2="${pad.top}"></line>
                            <line x1="${pad.left}" y1="${pad.top + (height - pad.top - pad.bottom) / 2}" x2="${width - pad.right}" y2="${pad.top + (height - pad.top - pad.bottom) / 2}"></line>
                            <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"></line>
                        </g>
                        <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#d8e1eb"></line>
                        <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#d8e1eb"></line>
                        <g class="native-chart-lines">${paths}</g>
                        <g class="native-chart-ticks">${ticks}</g>
                    </svg>
                </div>`;
        },
        nativePiesHtml(groups) {
            const width = 760;
            const height = 330;
            const pies = groups.map((group, groupIndex) => {
                const cx = groupIndex === 0 ? 230 : 540;
                const cy = 145;
                const total = group.items.reduce((sum, item) => sum + Number(item.value || 0), 0);
                const items = total ? group.items : [{ name: group.emptyText, value: 1, color: "#d8ded6" }];
                let cursor = -Math.PI / 2;
                const paths = items.map((item) => {
                    const value = Number(item.value || 0);
                    const next = cursor + value / (total || 1) * Math.PI * 2;
                    const path = this.donutSegment(cx, cy, 82, 52, cursor, next, item.color, `${item.name}: ${value}`);
                    cursor = next;
                    return path;
                }).join("");
                return `
                    <g>
                        ${paths}
                        <text x="${cx}" y="${cy - 4}" text-anchor="middle" class="native-pie-title">${this.escapeHtml(group.title)}</text>
                        <text x="${cx}" y="${cy + 20}" text-anchor="middle" class="native-pie-total">${total || 0}</text>
                    </g>`;
            }).join("");
            const legend = groups.flatMap((group) => group.items).map((item) => `<span><i style="background:${item.color}"></i>${this.escapeHtml(item.name)}</span>`).join("");
            return `
                <div class="native-chart-layer">
                    <svg class="native-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="统计饼图">${pies}</svg>
                    <div class="native-chart-legend native-pie-legend">${legend}</div>
                </div>`;
        },
        requestVisualRefresh(delay = 0) {
            if (this.visualRefreshTimer) clearTimeout(this.visualRefreshTimer);
            this.visualRefreshTimer = setTimeout(() => {
                this.visualRefreshTimer = null;
                this.stabilizeVisuals(() => this.renderActiveVisuals());
            }, delay);
        },
        stabilizeVisuals(callback) {
            nextTick(() => {
                const run = () => {
                    callback();
                    this.invalidateVisualSizes();
                    setTimeout(() => this.invalidateVisualSizes(), 120);
                    setTimeout(callback, 220);
                    setTimeout(() => {
                        callback();
                        this.invalidateVisualSizes();
                    }, 420);
                };
                if (window.requestAnimationFrame) requestAnimationFrame(run);
                else setTimeout(run, 0);
            });
        },
        invalidateVisualSizes() {
            if (this.map) this.map.invalidateSize();
            Object.values(this.charts).forEach((chart) => chart?.resize?.());
        },
        renderActiveVisuals() {
            this.observeVisualNodes();
            if (this.page === "dashboard" && this.state.dashboard) this.renderDashboardVisuals();
            if (this.page === "history" && this.state.history) this.renderHistoryCharts();
            if (this.page === "reports" && this.state.reports) this.renderReportChart();
        },
        observeVisualNodes() {
            if (!window.ResizeObserver) return;
            if (!this.visualResizeObserver) {
                this.visualResizeObserver = new ResizeObserver(() => this.invalidateVisualSizes());
            }
            ["flowChart", "historyChart", "reconstructionChart", "reportChart", "deviceMap"].forEach((refName) => {
                const node = this.chartNode(refName);
                if (node && !node.dataset.visualObserved) {
                    node.dataset.visualObserved = "1";
                    this.visualResizeObserver.observe(node);
                }
            });
        },
        renderDashboardVisuals() {
            this.renderMap();
            this.renderDashboardCharts();
        },
        chartNode(refName) {
            const ref = this.$refs[refName];
            return Array.isArray(ref) ? ref[0] : ref;
        },
        chart(refName) {
            const node = this.chartNode(refName);
            if (!node || !window.echarts) return null;
            const rect = node.getBoundingClientRect();
            if (rect.width < 20 || rect.height < 80) return null;
            const current = this.charts[refName];
            if (current && current.getDom && current.getDom() === node) return current;
            if (current) current.dispose();
            this.charts[refName] = echarts.init(node);
            return this.charts[refName];
        },
        disposeCharts() {
            Object.values(this.charts).forEach((chart) => chart?.dispose?.());
            this.charts = {};
        },
        baseChartOption(emptyText = "暂无数据") {
            return {
                backgroundColor: "transparent",
                animation: false,
                grid: { left: 42, right: 20, top: 42, bottom: 42, containLabel: true },
                tooltip: { trigger: "axis", borderWidth: 0, backgroundColor: "rgba(15,23,42,.92)", textStyle: { color: "#fff" } },
                legend: { top: 8, right: 12, textStyle: { color: "#64748b" } },
                xAxis: { type: "category", axisLine: { lineStyle: { color: "#d8e1eb" } }, axisTick: { show: false }, axisLabel: { color: "#64748b" } },
                yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf2f7" } }, axisLabel: { color: "#64748b" } },
                graphic: { type: "text", left: "center", top: "middle", invisible: true, style: { text: emptyText, fill: "#6f746f", fontWeight: 760 } },
            };
        },
        setChart(refName, option, hasData, emptyText = "暂无数据") {
            const chart = this.chart(refName);
            if (!chart) {
                setTimeout(() => this.renderActiveVisuals(), 120);
                return;
            }
            chart.setOption({
                ...option,
                graphic: {
                    ...(option.graphic || {}),
                    type: "text",
                    left: "center",
                    top: "middle",
                    invisible: Boolean(hasData),
                    style: { text: emptyText, fill: "#6f746f", fontWeight: 760, fontSize: 13 },
                },
            }, { notMerge: true, lazyUpdate: false });
            chart.resize();
        },
        renderDashboardCharts() {
            const base = this.baseChartOption();
            const cards = this.dashboardCards.slice(0, 12);
            this.setChart("flowChart", {
                ...base,
                grid: { left: 42, right: 20, top: 20, bottom: 68, containLabel: true },
                xAxis: { ...base.xAxis, data: cards.map((item) => item.meter_id || "-"), axisLabel: { color: "#64748b", rotate: 28 } },
                yAxis: { ...base.yAxis },
                series: [{
                    name: "瞬时流量",
                    type: "bar",
                    data: cards.map((item) => Number(item.instant_flow || 0)),
                    itemStyle: { color: "#0f766e", borderRadius: [5, 5, 0, 0] },
                    barMaxWidth: 42,
                }],
            }, cards.length > 0, "暂无设备流量数据");

        },
        ensureNativeChartsVisible() {
            const charts = this.$el?.querySelectorAll?.(".chart-native");
            if (!charts) return;
            charts.forEach((chart) => {
                chart.style.display = "block";
                if (!chart.innerHTML.trim()) {
                    chart.innerHTML = `<div class="native-chart-layer"><div class="native-chart-empty">暂无数据</div></div>`;
                }
            });
        },
        renderMap() {
            const node = this.$refs.deviceMap;
            const points = this.filteredMapPoints;
            if (!node) return;
            const rect = node.getBoundingClientRect();
            if (rect.width < 20 || rect.height < 120) {
                setTimeout(() => this.renderMap(), 160);
                return;
            }
            if (!window.L) {
                this.renderFallbackMap(node, points, "Leaflet 未加载，已切换到离线设备态势图");
                return;
            }
            node.classList.remove("map-native", "map-fallback");
            if (this.map && this.map.getContainer && this.map.getContainer() !== node) {
                this.destroyLeafletMap();
            }
            try {
                if (!this.map) {
                    node.innerHTML = "";
                    this.mapTileErrors = 0;
                    this.map = L.map(node, { zoomControl: false, attributionControl: true }).setView(MAP_CENTER, 12);
                    L.control.zoom({ position: "bottomright" }).addTo(this.map);
                    this.mapTileLayer = L.tileLayer(AMAP_TILE_URL, {
                        maxZoom: 18,
                        minZoom: 3,
                        subdomains: AMAP_TILE_SUBDOMAINS,
                        attribution: "高德地图",
                    });
                    this.mapTileLayer.on("tileerror", () => {
                        this.mapTileErrors += 1;
                        if (this.mapTileErrors >= MAP_TILE_ERROR_LIMIT) {
                            console.warn("Map tiles are still loading or failed temporarily; keeping the tiled map container alive.");
                        }
                    });
                    this.mapTileLayer.on("load", () => {
                        this.mapTileErrors = 0;
                        if (this.mapFallbackTimer) clearTimeout(this.mapFallbackTimer);
                        this.mapFallbackTimer = null;
                    });
                    this.mapTileLayer.addTo(this.map);
                    this.mapFallbackTimer = setTimeout(() => {
                        if (this.map && !node.querySelector(".leaflet-tile-loaded")) {
                            this.map.invalidateSize();
                        }
                    }, 6000);
                }
                this.renderLeafletPoints(points);
                setTimeout(() => this.map?.invalidateSize(), 80);
                setTimeout(() => this.map?.invalidateSize(), 260);
            } catch (error) {
                console.warn("Map initialization failed, using local fallback map.", error);
                this.renderFallbackMap(node, points, "地图初始化异常，已切换到离线设备态势图");
            }
        },
        renderLeafletPoints(points) {
            if (!this.map || !window.L) return;
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
                }).bindPopup(`<strong>${this.escapeHtml(point.meter_id)}</strong><br>${this.escapeHtml(point.name || "")}<br>${this.escapeHtml(point.location || "")}`).addTo(this.mapLayer);
            });
            if (bounds.length) {
                this.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
            } else {
                this.map.setView(MAP_CENTER, 11);
            }
        },
        destroyLeafletMap(node) {
            if (this.mapTileLoadTimer) clearTimeout(this.mapTileLoadTimer);
            if (this.mapFallbackTimer) clearTimeout(this.mapFallbackTimer);
            if (this.map) this.map.remove();
            this.map = null;
            this.mapLayer = null;
            this.mapTileLayer = null;
            this.mapTileErrors = 0;
            this.mapTileLoadTimer = null;
            this.mapFallbackTimer = null;
            if (node) node.innerHTML = "";
        },
        renderFallbackMap(node, points, message = "离线底图模式 · 设备坐标仍可展示") {
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
            layer.innerHTML = `<div class="native-map-title">设备地理态势</div><div class="native-map-subtitle">${this.escapeHtml(message)}</div>`;
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
            const base = this.baseChartOption();
            const rows = this.recentHistoryRows;
            this.setChart("historyChart", {
                ...base,
                xAxis: { ...base.xAxis, data: rows.map((item) => this.shortDate(item.timestamp)) },
                yAxis: { ...base.yAxis },
                series: [
                    {
                        name: "瞬时流量",
                        type: "line",
                        smooth: true,
                        data: rows.map((item) => Number(item.instant_flow || 0)),
                        lineStyle: { color: "#0f766e", width: 3 },
                        itemStyle: { color: "#0f766e" },
                    },
                    {
                        name: "管网压力",
                        type: "line",
                        smooth: true,
                        data: rows.map((item) => Number(item.pressure || 0)),
                        lineStyle: { color: "#2563eb", width: 3 },
                        itemStyle: { color: "#2563eb" },
                    },
                    {
                        name: "电池电压",
                        type: "line",
                        smooth: true,
                        data: rows.map((item) => Number(item.battery_voltage || 0)),
                        lineStyle: { color: "#d97706", width: 3 },
                        itemStyle: { color: "#d97706" },
                    },
                ],
            }, rows.length > 0, "暂无历史读数数据");

            const reconstruction = this.reconstructionSeries;
            const hasReconstruction = reconstruction.original.length || reconstruction.rebuilt.length || reconstruction.errors.length;
            this.setChart("reconstructionChart", {
                ...base,
                xAxis: { ...base.xAxis, data: reconstruction.labels },
                yAxis: { ...base.yAxis },
                series: [
                    {
                        name: "原始流量",
                        type: "line",
                        smooth: true,
                        data: reconstruction.original.map((item) => Number(item || 0)),
                        lineStyle: { color: "#0f766e", width: 3 },
                        itemStyle: { color: "#0f766e" },
                    },
                    {
                        name: "重构流量",
                        type: "line",
                        smooth: true,
                        data: reconstruction.rebuilt.map((item) => Number(item || 0)),
                        lineStyle: { color: "#2563eb", width: 3 },
                        itemStyle: { color: "#2563eb" },
                    },
                    {
                        name: "重构误差",
                        type: "bar",
                        data: reconstruction.errors.map((item) => Number(item || 0)),
                        itemStyle: { color: "#dc2626", borderRadius: [4, 4, 0, 0] },
                        barMaxWidth: 24,
                    },
                ],
            }, hasReconstruction, reconstruction.emptyText);
        },
        renderReportChart() {
            const report = this.state.reports || {};
            const orders = report.order_summary || {};
            const severity = report.severity_summary || {};
            const reportNode = this.chartNode("reportChart");
            const reportWidth = reportNode?.getBoundingClientRect?.().width || 760;
            const isNarrow = reportWidth < 620;
            const orderData = [
                { name: "未完成", value: Number(orders.open_orders || 0), itemStyle: { color: "#2563eb" } },
                { name: "已完成", value: Number(orders.completed_orders || 0), itemStyle: { color: "#0f766e" } },
            ];
            const severityData = [
                { name: "紧急", value: Number(severity.high || 0), itemStyle: { color: "#dc2626" } },
                { name: "重要", value: Number(severity.medium || 0), itemStyle: { color: "#d97706" } },
                { name: "一般", value: Number(severity.low || 0), itemStyle: { color: "#64748b" } },
            ];
            this.setChart("reportChart", {
                backgroundColor: "transparent",
                animation: false,
                tooltip: { trigger: "item", borderWidth: 0, backgroundColor: "rgba(15,23,42,.92)", textStyle: { color: "#fff" } },
                legend: { bottom: 0, textStyle: { color: "#64748b" } },
                series: [
                    { name: "工单状态", type: "pie", radius: isNarrow ? ["25%", "38%"] : ["42%", "66%"], center: isNarrow ? ["50%", "28%"] : ["28%", "45%"], data: orderData },
                    { name: "告警等级", type: "pie", radius: isNarrow ? ["25%", "38%"] : ["42%", "66%"], center: isNarrow ? ["50%", "66%"] : ["72%", "45%"], data: severityData },
                ],
            }, orderData.some((item) => item.value) || severityData.some((item) => item.value), "暂无报表数据");
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

        <section class="content" :class="{loading: pageLoading}">
            <header class="topbar">
                <div><p class="eyebrow">Smart Gas Monitoring</p><h1>{{ currentPage.label }}</h1></div>
                <div class="topbar-actions"><span class="live-dot" :class="{muted: realtimeText !== '实时在线'}">{{ realtimeText }}</span><span v-if="isEngineer" class="user-chip">{{ user.engineer_online ? '工程师在线' : '工程师离线' }}</span><span class="user-chip">{{ user.full_name }} · {{ roleLabel(user.role) }}</span><button class="ghost" @click="logout">退出</button></div>
            </header>

            <div v-if="pageLoading" class="loading-bar" aria-hidden="true"></div>
            <p v-if="message" class="error-text">{{ message }}</p>

            <section v-if="page === 'dashboard' && state.dashboard" :key="'dashboard-' + loadRequestId" class="dashboard-grid">
                <div class="stats-row">
                    <article class="stat"><span>在线设备</span><strong>{{ summary.connected_devices || 0 }}</strong><em>实时上报</em></article>
                    <article class="stat"><span>离线设备</span><strong>{{ summary.offline_devices || 0 }}</strong><em>需关注</em></article>
                    <article class="stat danger"><span>异常设备</span><strong>{{ summary.abnormal_devices || 0 }}</strong><em>模型判定</em></article>
                    <article class="stat"><span>待办工单</span><strong>{{ openOrders }}</strong><em>闭环处置</em></article>
                </div>
                <section class="panel map-panel"><div class="panel-title"><div><h2>设备地理分布</h2><p>{{ summary.total_devices || 0 }} 台设备 · 在线/离线/异常状态</p></div><div class="map-actions"><div class="segmented"><button :class="{active: filters.mapStatus === 'all'}" @click="filters.mapStatus = 'all'; requestVisualRefresh()">全部 {{ mapFilterCounts.all }}</button><button :class="{active: filters.mapStatus === 'online'}" @click="filters.mapStatus = 'online'; requestVisualRefresh()">在线 {{ mapFilterCounts.online }}</button><button :class="{active: filters.mapStatus === 'offline'}" @click="filters.mapStatus = 'offline'; requestVisualRefresh()">离线 {{ mapFilterCounts.offline }}</button><button :class="{active: filters.mapStatus === 'anomaly'}" @click="filters.mapStatus = 'anomaly'; requestVisualRefresh()">异常 {{ mapFilterCounts.anomaly }}</button></div><button class="ghost" @click="loadPage">刷新</button></div></div><div ref="deviceMap" class="map"></div></section>
                <section class="panel"><div class="panel-title"><div><h2>瞬时流量排行</h2><p>最近上报 Top 12</p></div></div><div ref="flowChart" class="chart chart-runtime"></div></section>
                <section class="panel"><div class="panel-title"><div><h2>告警趋势</h2><p>最近 24 小时</p></div></div><div class="chart chart-native compact" v-html="dashboardTrendChartHtml"></div></section>
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
                <form v-if="canAdmin" class="panel form-panel" @submit.prevent="saveWorkOrder"><div class="panel-title"><div><h2>工单编辑</h2><p>自动按工程师住址距离派单</p></div><button type="button" class="ghost" @click="resetWorkOrderForm">清空</button></div><input v-model.trim="forms.workOrder.title" placeholder="工单标题" required><textarea v-model.trim="forms.workOrder.description" placeholder="问题描述" required></textarea><select v-model="forms.workOrder.priority"><option value="high">高优先级</option><option value="medium">中优先级</option><option value="low">低优先级</option></select><select v-model="forms.workOrder.status"><option value="pending">待处理</option><option value="assigned">已派单</option><option value="in_progress">处理中</option><option value="completed">已完成</option></select><select v-model="forms.workOrder.device_id" required><option value="">选择设备</option><option v-for="device in state.devices" :key="device.id" :value="device.id">{{ device.meter_id }} · {{ device.location }}</option></select><select v-model="forms.workOrder.engineer_id"><option value="">自动按距离分配</option><option v-for="engineer in state.engineers" :key="engineer.id" :value="engineer.id">{{ engineer.name }} · {{ engineer.address }} · {{ engineer.active_orders }} 单</option></select><button>保存工单</button></form>
                <section class="panel"><div class="panel-title"><div><h2>工单列表</h2><p>从告警到处置结果回写</p></div><span>{{ filteredWorkOrders.length }} 条</span></div><article v-for="order in filteredWorkOrders" :key="order.id" class="record"><strong>{{ order.title }} · {{ priorityLabel(order.priority) }}</strong><span>{{ statusLabel(order.status) }} · {{ order.meter_id }} · {{ order.engineer_name || '未分配' }}</span><p>{{ order.description }}</p><div class="flow"><span v-for="node in order.flow_nodes" :key="node.stage" :class="{active: node.active, current: node.current}">{{ node.label }}</span></div><button v-if="canAdmin" @click="editWorkOrder(order)">编辑</button><button v-if="canAdmin" class="ghost danger-text" @click="deleteWorkOrder(order)">删除</button><button v-if="isEngineer && order.status === 'assigned'" @click="acceptOrder(order)">接单</button><button v-if="isEngineer && order.status === 'in_progress'" @click="completeOrder(order)">完成</button></article><div v-if="!filteredWorkOrders.length" class="empty">暂无工单</div></section>
            </section>

            <section v-if="page === 'engineers'" class="panel"><div class="panel-title"><div><h2>工程师状态</h2><p>工程师账号自动生成档案，展示在线状态与当前负载</p></div><span>{{ state.engineers.length }} 人</span></div><div class="card-grid"><article v-for="engineer in state.engineers" :key="engineer.id" class="mini-card"><strong>{{ engineer.name }}</strong><span>{{ engineer.employee_no }} · {{ engineer.phone }}</span><p>{{ engineer.is_online ? '在线' : '离线' }} · 当前工单 {{ engineer.active_orders }}</p><p>{{ engineer.address }}</p></article></div><div v-if="!state.engineers.length" class="empty">暂无工程师档案，请在用户权限中创建工程师账号。</div></section>

            <section v-if="page === 'history'" :key="'history-' + loadRequestId" class="panel"><div class="panel-title"><div><h2>历史数据与重构分析</h2><p>对比原始流量、重构流量和重构误差</p></div><select v-model="filters.meterId" @change="loadHistory"><option value="">全部设备</option><option v-for="device in state.devices" :key="device.id" :value="device.meter_id">{{ device.meter_id }}</option></select></div><div class="charts-2"><div ref="historyChart" class="chart chart-runtime"></div><div ref="reconstructionChart" class="chart chart-runtime"></div></div><div v-if="state.reconstruction && !state.reconstruction.ready" class="empty">{{ state.reconstruction.message || '重构分析需要更多连续读数。' }}</div><div class="table-wrap compact-table"><table><thead><tr><th>设备</th><th>时间</th><th>流量</th><th>压力</th><th>电压</th><th>异常得分</th><th>模型</th></tr></thead><tbody><tr v-for="row in historyRows.slice(-24).reverse()" :key="row.meter_id + row.timestamp"><td>{{ row.meter_id }}</td><td>{{ date(row.timestamp) }}</td><td>{{ number(row.instant_flow, 4) }}</td><td>{{ number(row.pressure) }}</td><td>{{ number(row.battery_voltage) }}</td><td>{{ number(row.anomaly_score) }}</td><td>{{ row.model_version || '-' }}</td></tr></tbody></table></div></section>

            <section v-if="page === 'reports'" :key="'reports-' + loadRequestId" class="panel"><div class="panel-title"><div><h2>统计报表</h2><p>告警等级和工单闭环效率概览</p></div></div><div class="report-summary"><article><span>工单总数</span><strong>{{ state.reports?.order_summary?.total_orders || 0 }}</strong></article><article><span>未完成</span><strong>{{ state.reports?.order_summary?.open_orders || 0 }}</strong></article><article><span>已完成</span><strong>{{ state.reports?.order_summary?.completed_orders || 0 }}</strong></article><article><span>紧急告警</span><strong>{{ state.reports?.severity_summary?.high || 0 }}</strong></article></div><div ref="reportChart" class="chart chart-runtime large"></div></section>

            <section v-if="page === 'settings'" class="settings-grid">
                <section class="panel modules-panel"><div class="panel-title"><div><h2>模块控制</h2><p>仿真接入、持续训练、MQTT 网关与漂移监控</p></div></div><div class="card-grid"><article class="mini-card"><strong>虚拟设备模拟器</strong><span>{{ moduleRunning(state.simulator) ? '运行中' : '已停止' }}</span><button @click="controlModule('simulator', moduleRunning(state.simulator) ? 'stop' : 'start')">{{ moduleRunning(state.simulator) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>持续训练流水线</strong><span>{{ moduleRunning(state.training) ? '运行中' : '已停止' }}</span><button @click="controlModule('training', moduleRunning(state.training) ? 'stop' : 'start')">{{ moduleRunning(state.training) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>MQTT 网关</strong><span>{{ moduleRunning(state.mqtt) ? '运行中' : '已停止' }}</span><button @click="controlModule('mqtt', moduleRunning(state.mqtt) ? 'stop' : 'start')">{{ moduleRunning(state.mqtt) ? '停止' : '启动' }}</button></article><article class="mini-card"><strong>数据漂移监控</strong><span>{{ moduleRunning(state.drift) ? '运行中' : '已停止' }}</span><button @click="controlModule('drift', moduleRunning(state.drift) ? 'stop' : 'start')">{{ moduleRunning(state.drift) ? '停止' : '启动' }}</button><button class="ghost" @click="controlModule('drift', 'check')">立即检查</button></article></div></section>
                <section class="panel"><div class="panel-title"><div><h2>系统状态</h2><p>数据与模型运行概览</p></div></div><div class="kv"><span>用户数</span><strong>{{ state.settings?.user_count }}</strong><span>物理数据</span><strong>{{ state.settings?.physical_data_count }}</strong><span>训练原始数据</span><strong>{{ state.settings?.training_raw_data_count }}</strong><span>清洗数据</span><strong>{{ state.settings?.training_clean_data_count }}</strong><span>激活模型</span><strong>{{ activeModel }}</strong><span>F1</span><strong>{{ number(state.settings?.active_model_f1) }}</strong></div></section>
                <section class="panel wide-settings"><div class="panel-title"><div><h2>模型版本</h2><p>LSTM AutoEncoder 注册表最近版本</p></div><span>最近 10 个</span></div><div class="table-wrap"><table><thead><tr><th>模型</th><th>创建时间</th><th>阈值</th><th>准确率</th><th>Precision</th><th>Recall</th><th>F1</th><th>状态</th></tr></thead><tbody><tr v-for="model in state.settings?.model_versions || []" :key="model.model_id"><td>{{ model.model_id }}</td><td>{{ date(model.created_at) }}</td><td>{{ number(model.threshold, 4) }}</td><td>{{ number(model.accuracy) }}</td><td>{{ number(model.precision) }}</td><td>{{ number(model.recall) }}</td><td>{{ number(model.f1) }}</td><td>{{ model.is_active ? '当前' : '候选' }}</td></tr></tbody></table></div></section>
            </section>

            <section v-if="page === 'users'" class="split">
                <form class="panel form-panel" @submit.prevent="saveUser"><div class="panel-title"><div><h2>用户编辑</h2><p>管理员与工程师账号分权</p></div><button type="button" class="ghost" @click="resetUserForm">清空</button></div><input v-model.trim="forms.user.username" placeholder="用户名，可留空自动生成"><input v-model.trim="forms.user.full_name" placeholder="姓名" required><input v-model="forms.user.password" type="password" placeholder="密码至少 6 位，需包含数字和英文；编辑可留空"><div class="form-grid"><select v-model="forms.user.role"><option value="sub_admin">管理员</option><option value="engineer">工程师</option></select><select v-model="forms.user.is_active"><option :value="true">启用</option><option :value="false">停用</option></select></div><div class="form-grid"><input v-model.trim="forms.user.employee_no" placeholder="工号" required><input v-model.trim="forms.user.phone" placeholder="电话" required></div><template v-if="forms.user.role === 'engineer'"><input v-model.trim="forms.user.address" placeholder="住址，用于按距离自动派单" required></template><button>保存用户</button></form>
                <section class="panel"><div class="panel-title"><div><h2>用户列表</h2><p>按角色控制页面和操作权限</p></div><span>{{ state.users.length }} 个账号</span></div><article v-for="item in state.users" :key="item.id" class="record"><strong>{{ item.full_name }}</strong><span>{{ item.username }} · {{ roleLabel(item.role) }} · {{ item.is_active ? '启用' : '停用' }}</span><button @click="editUser(item)">编辑</button><button v-if="item.role !== 'super_admin'" class="ghost danger-text" @click="deleteUser(item)">删除</button></article></section>
            </section>
        </section>
    </main>
    `,
});

appInstance.mount("#app");
document.getElementById("app")?.setAttribute("data-mounted", "1");
} catch (error) {
    console.error(error);
    if (window.renderBootError) window.renderBootError(error.message || String(error));
    else throw error;
}
