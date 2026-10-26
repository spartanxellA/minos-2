"""Proceso de workers: conectores (scrapers), análisis y motor de riesgo, sin servidor HTTP.

    python -m minos.worker

Necesita MINOS_REDIS_URL para pasarle los eventos en vivo a la API. Se pueden correr varias réplicas: los candados
en Redis evitan que dos consulten la misma fuente del mismo objetivo, y cada pedido de recálculo lo atiende una sola.
"""
import asyncio
import logging
import signal

from .config import get_settings
from .runtime import Runtime

log = logging.getLogger("minos.worker")


async def main() -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise SystemExit("python -m minos.worker necesita MINOS_REDIS_URL; sin Redis usa MINOS_ROLE=all en la API.")
    runtime = await Runtime.start(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    runtime.start_workers()
    try:
        await stop.wait()
        log.info("Deteniendo workers…")
    finally:
        await runtime.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
