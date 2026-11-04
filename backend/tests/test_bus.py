"""El bus en Redis: eventos en vivo, cola de recálculo con varias réplicas y candados.

Usa fakeredis; con MINOS_TEST_REDIS_URL corre contra un Redis real (como en CI)."""
import asyncio
import json
import os
import uuid

import fakeredis
import pytest
from redis.asyncio import Redis

from minos.bus import MemoryBus, RedisBus
from minos.schemas import TopicCount

REDIS_URL = os.getenv("MINOS_TEST_REDIS_URL", "")


@pytest.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else fakeredis.FakeAsyncRedis(decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


def bus(redis, name: str) -> RedisBus:
    return RedisBus("", consumer=name, client=redis)


async def test_live_events_reach_every_api_instance(redis):
    target = uuid.uuid4()
    got_a, got_b = asyncio.Queue(), asyncio.Queue()

    async def to(queue):
        async def deliver(target_id, message):
            await queue.put((target_id, message))
        return deliver

    listeners = [asyncio.create_task(bus(redis, "api-a").listen(await to(got_a))),
                 asyncio.create_task(bus(redis, "api-b").listen(await to(got_b)))]
    await asyncio.sleep(0.2)  # que ambas suscripciones estén activas

    await bus(redis, "worker").publish(target, "riskUpdated", TopicCount(topic="fraude", count=2))

    for queue in (got_a, got_b):
        target_id, message = await asyncio.wait_for(queue.get(), 2)
        assert target_id == target
        assert json.loads(message) == {"event": "riskUpdated", "data": {"topic": "fraude", "count": 2}}
    for t in listeners:
        t.cancel()
    await asyncio.gather(*listeners, return_exceptions=True)


async def test_each_recompute_request_goes_to_one_replica(redis):
    worker_a, worker_b = bus(redis, "a"), bus(redis, "b")
    await worker_a.next_recompute(0.01)  # crea el grupo de consumidores
    targets = [uuid.uuid4() for _ in range(6)]
    for t in targets:
        await bus(redis, "ingesta").request_recompute(t)

    seen_a = await worker_a.next_recompute(0.2)
    seen_b = await worker_b.next_recompute(0.2)

    assert seen_a | seen_b == set(targets)
    assert not seen_a & seen_b
    assert await worker_a.next_recompute(0.05) == set()


async def test_locks_are_exclusive_and_only_the_owner_releases(redis):
    a, b = bus(redis, "a"), bus(redis, "b")
    assert await a.try_lock("ingest:t:x", 5)
    assert not await b.try_lock("ingest:t:x", 5)
    await b.release("ingest:t:x")  # no es suyo: no hace nada
    assert not await b.try_lock("ingest:t:x", 5)
    await a.release("ingest:t:x")
    assert await b.try_lock("ingest:t:x", 5)


async def test_only_the_owner_renews_a_lock(redis):
    a, b = bus(redis, "a"), bus(redis, "b")
    assert await a.try_lock("stream:jetstream", 0.2)
    assert not await b.renew("stream:jetstream", 5)
    assert await a.renew("stream:jetstream", 5)
    await asyncio.sleep(0.3)
    assert not await b.try_lock("stream:jetstream", 5)  # sigue siendo de "a" gracias a la renovación
    await redis.delete("minos:lock:stream:jetstream")
    assert not await a.renew("stream:jetstream", 5)  # vencido: hay que volver a tomarlo


async def test_memory_bus_batches_pending_recomputes():
    memory = MemoryBus()
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    for t in (t1, t2, t1):
        await memory.request_recompute(t)
    assert await memory.next_recompute(0.1) == {t1, t2}
    assert await memory.next_recompute(0.01) == set()


@pytest.mark.parametrize("kind", ["memory", "redis"])
async def test_counters_expire_and_are_shared_by_every_api_instance(redis, kind):
    a, b = (MemoryBus(),) * 2 if kind == "memory" else (bus(redis, "api-1"), bus(redis, "api-2"))
    assert [await a.hit("login:ip:x", 0.3), await b.hit("login:ip:x", 0.3), await a.hit("login:ip:x", 0.3)] == [1, 2, 3]
    await asyncio.sleep(0.4)
    assert await b.hit("login:ip:x", 60) == 1  # venció y empezó de nuevo

    assert await a.blocked_for("login:lock:ip:x") == 0
    await a.block("login:lock:ip:x", 60)
    assert 59 < await b.blocked_for("login:lock:ip:x") <= 60

    await b.block("login:lock:pair:e1:i1", 60)
    await b.block("login:lock:pair:e1:i2", 60)
    await b.block("login:lock:pair:e2:i1", 60)
    await a.forget("login:lock:pair:e1:")
    assert [await b.blocked_for(k) for k in ("login:lock:pair:e1:i1", "login:lock:pair:e1:i2")] == [0, 0]
    assert await b.blocked_for("login:lock:pair:e2:i1") > 0
