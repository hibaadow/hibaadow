"""Standalone trading worker: ``python -m atlas.worker``.

Use with ``ATLAS_EMBEDDED_WORKER=false`` on the API so exactly one engine runs.
Events reach the API (and browsers) through Redis pub/sub.
"""
from __future__ import annotations

import asyncio
import signal

from .agent import TradingAgent
from .db import init_db
from .logging import get_logger, setup_logging

log = get_logger("atlas.worker")


async def main() -> None:
    setup_logging()
    init_db()
    agent = TradingAgent()
    await agent.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker running")
    await stop.wait()
    log.info("worker stopping")
    await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
