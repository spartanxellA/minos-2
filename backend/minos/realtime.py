"""Canal en vivo del tablero por WebSocket.

Cada cliente se conecta a /ws/targets/{id} y recibe mensajes {"event": ..., "data": ...} con los eventos
"riskUpdated", "mentionsAdded" y "alertRaised". Los eventos llegan por el bus (minos/bus.py): en memoria cuando todo
corre en un proceso, o por Redis pub/sub cuando los workers corren aparte o hay varias instancias de la API.
"""
import asyncio
import logging
import uuid
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)


class RiskHub:
    """Los WebSocket abiertos en esta instancia de la API, agrupados por objetivo."""

    def __init__(self) -> None:
        self._groups: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    def subscribe(self, target_id: uuid.UUID, ws: WebSocket) -> None:
        self._groups[target_id].add(ws)

    def unsubscribe(self, target_id: uuid.UUID, ws: WebSocket) -> None:
        group = self._groups.get(target_id)
        if group is not None:
            group.discard(ws)
            if not group:
                del self._groups[target_id]

    def subscribers(self, target_id: uuid.UUID) -> int:
        return len(self._groups.get(target_id, ()))

    async def deliver(self, target_id: uuid.UUID, message: str) -> None:
        sockets = list(self._groups.get(target_id, ()))
        if not sockets:
            return
        results = await asyncio.gather(*(ws.send_text(message) for ws in sockets), return_exceptions=True)
        for ws, result in zip(sockets, results):
            if isinstance(result, Exception):
                log.debug("Cliente desconectado: %s", result)
                self.unsubscribe(target_id, ws)
