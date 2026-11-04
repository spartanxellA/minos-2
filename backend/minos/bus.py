"""Comunicación entre la API y los workers.

Tres piezas, cada una en memoria (un solo proceso) o en Redis (API y workers por separado, varias réplicas):

- Eventos en vivo: los workers publican "riskUpdated", "mentionsAdded" y "alertRaised"; cada instancia de la API
  los recibe (Redis pub/sub, canal minos:live) y los reenvía a sus clientes WebSocket.
- Cola de recálculo: la ingesta pide recalcular un objetivo (Redis Stream minos:recompute, grupo risk-engine), y
  solo una réplica del motor de riesgo lo atiende.
- Candados: evitan que dos réplicas de workers consulten la misma fuente para el mismo objetivo a la vez.
- Contadores con vencimiento: cuentan intentos fallidos de inicio de sesión (por IP, por correo) y guardan los
  bloqueos, compartidos por todas las réplicas de la API.
"""
import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

log = logging.getLogger(__name__)

LIVE_CHANNEL = "minos:live"
COUNTER_PREFIX = "minos:rl:"
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

    async def renew(self, key: str, ttl_seconds: float) -> bool:
        """Extiende un candado propio; falso si ya venció o lo tomó otra réplica."""
        return True

    async def release(self, key: str) -> None:
        return None

    @abstractmethod
    async def hit(self, key: str, window_seconds: float) -> int:
        """Suma uno al contador; el contador se borra solo window_seconds después del primer golpe. Da el total."""

    @abstractmethod
    async def block(self, key: str, ttl_seconds: float) -> None:
        """Marca key durante ttl_seconds."""

    @abstractmethod
    async def blocked_for(self, key: str) -> float:
        """Segundos que le quedan a la marca (o al contador) key; 0 si no hay."""

    @abstractmethod
    async def forget(self, prefix: str) -> None:
        """Borra contadores y marcas cuya llave empieza con prefix."""

    async def close(self) -> None:
        return None


class MemoryBus(Bus):
    """Todo en un proceso: la configuración de desarrollo y de pruebas."""

    def __init__(self) -> None:
        self._listeners: list[Deliver] = []
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._counters: dict[str, tuple[int, float]] = {}  # llave → (cuenta, vence en time.monotonic())

    def _alive(self, key: str) -> tuple[int, float] | None:
        entry = self._counters.get(key)
        if entry is not None and entry[1] <= time.monotonic():
            del self._counters[key]
            return None
        return entry

    async def hit(self, key: str, window_seconds: float) -> int:
        count, expires = self._alive(key) or (0, time.monotonic() + window_seconds)
        self._counters[key] = (count + 1, expires)
        return count + 1

    async def block(self, key: str, ttl_seconds: float) -> None:
        self._counters[key] = (1, time.monotonic() + ttl_seconds)

    async def blocked_for(self, key: str) -> float:
        entry = self._alive(key)
        return max(entry[1] - time.monotonic(), 0.0) if entry else 0.0

    async def forget(self, prefix: str) -> None:
        for key in [k for k in self._counters if k.startswith(prefix)]:
            del self._counters[key]

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

    async def renew(self, key: str, ttl_seconds: float) -> bool:
        from redis.exceptions import WatchError

        name = f"minos:lock:{key}"
        async with self._redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(name)
                if await pipe.get(name) != self._consumer:
                    return False
                pipe.multi()
                pipe.pexpire(name, max(int(ttl_seconds * 1000), 1))
                await pipe.execute()
                return True
            except WatchError:
                return False

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

    async def hit(self, key: str, window_seconds: float) -> int:
        name = COUNTER_PREFIX + key
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            # NX: el plazo corre desde el primer golpe; INCR y PEXPIRE van juntos para que no quede sin vencimiento.
            pipe.pexpire(name, max(int(window_seconds * 1000), 1), nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def block(self, key: str, ttl_seconds: float) -> None:
        await self._redis.set(COUNTER_PREFIX + key, "1", px=max(int(ttl_seconds * 1000), 1))

    async def blocked_for(self, key: str) -> float:
        ms = await self._redis.pttl(COUNTER_PREFIX + key)
        return ms / 1000 if ms and ms > 0 else 0.0

    async def forget(self, prefix: str) -> None:
        keys = [k async for k in self._redis.scan_iter(match=COUNTER_PREFIX + prefix + "*", count=500)]
        if keys:
            await self._redis.delete(*keys)

    async def close(self) -> None:
        await self._redis.aclose()


def create_bus(redis_url: str) -> Bus:
    return RedisBus(redis_url) if redis_url else MemoryBus()
