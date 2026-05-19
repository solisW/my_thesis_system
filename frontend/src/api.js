class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    async request(path, options = {}) {
        const response = await fetch(`${this.baseUrl}${path}`, {
            credentials: "include",
            headers: { "Content-Type": "application/json", ...(options.headers || {}) },
            ...options,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || `请求失败：${response.status}`);
        return payload;
    }

    post(path, body = {}) {
        return this.request(path, { method: "POST", body: JSON.stringify(body) });
    }

    put(path, body = {}) {
        return this.request(path, { method: "PUT", body: JSON.stringify(body) });
    }

    delete(path) {
        return this.request(path, { method: "DELETE" });
    }
}

window.ApiClient = ApiClient;
