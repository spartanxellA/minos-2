"""Comunicación entre la API y los workers.

Tres piezas, cada una en memoria (un solo proceso) o en Redis (API y workers por separado, varias réplicas):

- Eventos en vivo: los workers publican "riskUpdated", "mentionsAdded" y "alertRaised"; cada instancia de la API
  los recibe (Redis pub/sub, canal minos:live) y los reenvía a sus clientes WebSocket.
- Cola de recálculo: la ingesta pide recalcular un objetivo (Redis Stream minos:recompute, grupo risk-engine), y
  solo una réplica del motor de riesgo lo atiende.
- Candados: evitan que dos réplicas de workers consulten la misma fuente para el mismo objetivo a la vez.
"""
import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

log = logging.getLogger(__name__)

LIVE_CHANNEL = "minos:live"
RECOMPUTE_STREAM = "minos:recompute"
RECOMPUTE_GROUP = "risk-engine"
MAX_BLOCK_MS = 2_000

Deliver = Callable[[uuid.UUID, str], Awaitable[None]]


def encode_event(event: str, data: BaseModel | list[BaseModel]) -> str:
    """El mensaje tal como lo recibe el tablero: {"event": ..., "data": ...}."""
    if isinstance(data, list):
        payload = [d.model_dump(mode="json", by_alias=True) for d in data]
    else:
        payload = data.model_dump(mode="json", by_alias=True)
    return json.dumps({"event": event, "data": payload}, ensure_ascii=False)


class Bus(ABC):
    @abstractmethod
    async def publish(self, target_id: uuid.UUID, event: str, data: BaseModel | list[BaseModel]) -> None:
        """Manda un evento en vivo a todas las instancias de la API."""

    @abstractmethod
    async def listen(self, deliver: Deliver) -> None:
        """Corre en la API: entrega cada evento publicado a los WebSocket locales."""

    @abstractmethod
    async def request_recompute(self, target_id: uuid.UUID) -> None:
        """Pide recalcular el riesgo de un objetivo que recibió menciones nuevas."""

    @abstractmethod
    async def next_recompute(self, timeout: float) -> set[uuid.UUID]:
        """Objetivos pendientes de recalcular; vacío si no llegó nada en `timeout` segundos."""

    @abstractmethod
    async def try_lock(self, key: str, ttl_seconds: float) -> bool:
        """Toma un candado con vencimiento; falso si otra réplica ya lo tiene."""

    async def release(self, key: str) -> None:
        return None

    async def close(self) -> None:
        return None


class MemoryBus(Bus):
    """Todo en un proceso: la configuración de desarrollo y de pruebas."""

    def __init__(self) -> None:
        self._listeners: list[Deliver] = []
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()

    async def publish(self, target_id, event, data) -> None:
        message = encode_event(event, data)
        for deliver in list(self._listeners):
            await deliver(target_id, message)

    async def listen(self, deliver: Deliver) -> None:
        self._listeners.append(deliver)
        try:
            await asyncio.Event().wait()
        finally:
            self._listeners.remove(deliver)

    async def request_recompute(self, target_id) -> None:
        self._queue.put_nowait(target_id)

    async def next_recompute(self, timeout: float) -> set[uuid.UUID]:
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return set()
        pending = {first}
        while not self._queue.empty():
            pending.add(self._queue.get_nowait())
        return pending

    async def try_lock(self, key: str, ttl_seconds: float) -> bool:
        return True


class RedisBus(Bus):
    def __init__(self, url: str, consumer: str | None = None, client=None) -> None:
        if client is None:
            from redis.asyncio import Redis

            client = Redis.from_url(url, decode_responses=True)
        self._redis = client
        self._consumer = consumer or f"worker-{uuid.uuid4().hex[:8]}"
        self._group_ready = False

    async def publish(self, target_id, event, data) -> None:
        message = json.dumps({"target": str(target_id), "message": encode_event(event, data)}, ensure_ascii=False)
        await self._redis.publish(LIVE_CHANNEL, message)

    async def listen(self, deliver: Deliver) -> None:
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(LIVE_CHANNEL)
                async for item in pubsub.listen():
                    if item.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(item["data"])
                        await deliver(uuid.UUID(envelope["target"]), envelope["message"])
                    except (ValueError, KeyError):
                        log.warning("Evento en vivo inválido: %r", item.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # Redis reiniciado o caído: se reintenta sin tirar la API.
                log.warning("Se perdió la suscripción a Redis (%s); reintento en 2 s", ex)
                await asyncio.sleep(2)
            finally:
                await pubsub.aclose()

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        from redis.exceptions import ResponseError

        try:
            await self._redis.xgroup_create(RECOMPUTE_STREAM, RECOMPUTE_GROUP, id="0", mkstream=True)
        except ResponseError as ex:
            if "BUSYGROUP" not in str(ex):
                raise
        self._group_ready = True

    async def request_recompute(self, target_id) -> None:
        # MAXLEN acota el stream: los pedidos viejos ya se atendieron o los cubre el recálculo completo.
        await self._redis.xadd(RECOMPUTE_STREAM, {"target": str(target_id)}, maxlen=10_000, approximate=True)

    async def next_recompute(self, timeout: float) -> set[uuid.UUID]:
        await self._ensure_group()
        # Bloqueos cortos: redis-py corta las lecturas largas, y quien llama vuelve a preguntar en su ciclo.
        block_ms = min(max(int(timeout * 1000), 1), MAX_BLOCK_MS)
        response = await self._redis.xreadgroup(
            RECOMPUTE_GROUP, self._consumer, {RECOMPUTE_STREAM: ">"}, count=200, block=block_ms
        )
        pending: set[uuid.UUID] = set()
        ids = []
        for _stream, entries in response or []:
            for entry_id, fields in entries:
                ids.append(entry_id)
                try:
                    pending.add(uuid.UUID(fields["target"]))
                except (KeyError, ValueError):
                    log.warning("Pedido de recálculo inválido: %r", fields)
        if ids:
            # Se confirma al leer: recalcular es idempotente y el recálculo completo periódico cubre cualquier pérdida.
            await self._redis.xack(RECOMPUTE_STREAM, RECOMPUTE_GROUP, *ids)
        return pending

    async def try_lock(self, key: str, ttl_seconds: float) -> bool:
        return bool(await self._redis.set(f"minos:lock:{key}", self._consumer, nx=True, px=max(int(ttl_seconds * 1000), 1)))

    async def release(self, key: str) -> None:
        # Solo se borra si el candado sigue siendo nuestro (WATCH: si cambia entre GET y DEL, no se borra).
        from redis.exceptions import WatchError

        name = f"minos:lock:{key}"
        async with self._redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(name)
                if await pipe.get(name) == self._consumer:
                    pipe.multi()
                    pipe.delete(name)
                    await pipe.execute()
            except WatchError:
                pass

    async def close(self) -> None:
        await self._redis.aclose()


def create_bus(redis_url: str) -> Bus:
    return RedisBus(redis_url) if redis_url else MemoryBus()
