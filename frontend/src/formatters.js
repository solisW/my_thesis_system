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

function numberText(value, digits = 2) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits) : "-";
}

function dateText(value) {
    return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
}

function shortDateText(value) {
    return value
        ? new Date(value).toLocaleString("zh-CN", {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        })
        : "-";
}

window.AppFormatters = {
    emptyState,
    userFormDefaults,
    workOrderDefaults,
    numberText,
    dateText,
    shortDateText,
};
