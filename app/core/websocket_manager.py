import asyncio
import logging
from typing import Any, Dict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[int, WebSocket] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            # Close previous connection for this user if any
            old = self._connections.get(user_id)
            if old is not None:
                try:
                    await old.close(code=1000, reason="Replaced by new connection")
                except Exception:
                    pass
            self._connections[user_id] = websocket
            logger.info("WebSocket connected — user_id=%s", user_id)

    async def disconnect(self, user_id: int) -> None:
        async with self._lock:
            self._connections.pop(user_id, None)
            logger.info("WebSocket disconnected — user_id=%s", user_id)

    async def is_connected(self, user_id: int) -> bool:
        async with self._lock:
            return user_id in self._connections

    async def send_json(self, user_id: int, data: Dict[str, Any]) -> bool:
        async with self._lock:
            ws = self._connections.get(user_id)
            if ws is None:
                return False
            try:
                await ws.send_json(data)
                return True
            except Exception as exc:
                logger.warning("WebSocket send failed for user_id=%s: %s", user_id, exc)
                self._connections.pop(user_id, None)
                return False

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        async with self._lock:
            disconnected = []
            for user_id, ws in list(self._connections.items()):
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.append(user_id)
            for uid in disconnected:
                self._connections.pop(uid, None)
