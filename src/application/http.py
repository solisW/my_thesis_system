from __future__ import annotations

import os

from flask import Flask, make_response, request


def register_cors(app: Flask) -> None:
    allowed_origins = {
        value.strip()
        for value in os.getenv(
            "FRONTEND_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if value.strip()
    }

    def is_origin_allowed(origin: str | None) -> bool:
        if not origin:
            return False
        return origin in allowed_origins

    def add_headers(response):
        origin = request.headers.get("Origin")
        if is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Carrier-Token"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    @app.before_request
    def handle_cors_preflight():
        if request.method == "OPTIONS" and is_origin_allowed(request.headers.get("Origin")):
            return add_headers(make_response("", 204))
        return None

    @app.after_request
    def add_cors_headers(response):
        return add_headers(response)
