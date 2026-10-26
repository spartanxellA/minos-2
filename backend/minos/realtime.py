"""Canal en vivo del tablero por WebSocket.

Cada cliente se conecta a /ws/targets/{id} y recibe mensajes {"event": ..., "data": ...} con los eventos
"riskUpdated", "mentionsAdded" y "alertRaised" en cuanto ocurren. Con varias instancias de la API, este
hub se reemplaza por Redis pub/sub sin cambiar el contrato.
"""
import asyncio
import json
import logging
import uuid
from collections import defaultdict

from fastapi import WebSocket
from pydantic import BaseModel

log = logging.getLogger(__name__)


class RiskHub:
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

    async def publish(self, target_id: uuid.UUID, event: str, data: BaseModel | list[BaseModel]) -> None:
        sockets = list(self._groups.get(target_id, ()))
        if not sockets:
            return
        if isinstance(data, list):
            payload = [d.model_dump(mode="json", by_alias=True) for d in data]
        else:
            payload = data.model_dump(mode="json", by_alias=True)
        message = json.dumps({"event": event, "data": payload}, ensure_ascii=False)
        results = await asyncio.gather(*(ws.send_text(message) for ws in sockets), return_exceptions=True)
        for ws, result in zip(sockets, results):
            if isinstance(result, Exception):
                log.debug("Cliente desconectado: %s", result)
                self.unsubscribe(target_id, ws)
