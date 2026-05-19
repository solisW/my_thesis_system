window.AppConfig = {
    API_BASE: window.API_BASE || "http://127.0.0.1:5000",
    MAP_COORD_SYSTEM: window.MAP_COORD_SYSTEM || "wgs84",
    AMAP_TILE_URL: window.AMAP_TILE_URL || "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
    AMAP_TILE_SUBDOMAINS: window.AMAP_TILE_SUBDOMAINS || ["1", "2", "3", "4"],
    MAP_CENTER: [31.2304, 121.4737],
    MAP_TILE_ERROR_LIMIT: 6,
};

window.AppPages = [
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
