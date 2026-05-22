class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = String(baseUrl || "").replace(/\/$/, "");
    }

    async request(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        let response;
        try {
            response = await fetch(url, {
                credentials: "include",
                headers: { "Content-Type": "application/json", ...(options.headers || {}) },
                ...options,
            });
        } catch (error) {
            throw new Error(this.networkErrorMessage(url, error));
        }

        const payload = await this.parsePayload(response);
        if (!response.ok) {
            throw new Error(payload.message || `请求失败：HTTP ${response.status}`);
        }
        return payload;
    }

    async parsePayload(response) {
        const contentType = response.headers.get("Content-Type") || "";
        if (!contentType.includes("application/json")) {
            const text = await response.text().catch(() => "");
            return text ? { message: text } : {};
        }
        return response.json().catch(() => ({}));
    }

    networkErrorMessage(url, error) {
        const target = new URL(url, window.location.href);
        if (window.location.protocol === "https:" && target.protocol === "http:") {
            return "无法连接后端：当前页面是 HTTPS，但 API 使用 HTTP，浏览器已拦截混合内容。请使用 http://127.0.0.1:5173 打开前端，或把后端也配置为 HTTPS。";
        }
        return [
            `无法连接后端 API：${target.origin}`,
            "请确认 start_system.bat 已启动并且后端窗口没有报错。",
            "如果后端已启动，请确认前端地址在 FRONTEND_ORIGINS 中，且 API_BASE 指向正确的后端地址。",
            error?.message ? `浏览器错误：${error.message}` : "",
        ].filter(Boolean).join("\n");
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
