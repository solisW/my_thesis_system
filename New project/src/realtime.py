from __future__ import annotations

import json
import threading

from flask_sock import Sock


sock = Sock()


class RealtimeHub:
    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = threading.Lock()

    def register(self, ws) -> None:
        with self._lock:
            self._clients.add(ws)

    def unregister(self, ws) -> None:
        with self._lock:
            self._clients.discard(ws)

    def broadcast(self, event: str, data) -> None:
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        with self._lock:
            clients = list(self._clients)

        stale = []
        for ws in clients:
            try:
                ws.send(message)
            except Exception:
                stale.append(ws)

        if stale:
            with self._lock:
                for ws in stale:
                    self._clients.discard(ws)


hub = RealtimeHub()
