"""Real-time event bus. Redis pub/sub when available (API and worker are separate
processes), otherwise an in-process broadcaster."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from .config import get_settings
from .logging import get_logger

log = get_logger("atlas.events")
CHANNEL = "atlas:events"


class LocalBus:
    def __init__(self):
        self._subs: set[asyncio.Queue] = set()

    async def publish(self, event: dict) -> None:
        for q in list(self._subs):
            if q.qsize() < 1000:
                q.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs.discard(q)


class RedisBus:
    def __init__(self, url: str):
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self._local = LocalBus()  # also deliver in-process (embedded worker)

    async def publish(self, event: dict) -> None:
        try:
            await self._redis.publish(CHANNEL, json.dumps(event, default=str))
        except Exception as e:  # noqa: BLE001
            log.warning("redis publish failed; delivering locally", extra={"data": {"error": str(e)[:120]}})
            await self._local.publish(event)

    async def subscribe(self) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    try:
                        yield json.loads(msg["data"])
                    except ValueError:
                        continue
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()


_bus = None


def get_bus():
    global _bus
    if _bus is None:
        url = get_settings().redis_url
        if url:
            try:
                import redis  # noqa: F401

                _bus = RedisBus(url)
            except Exception:  # noqa: BLE001
                _bus = LocalBus()
        else:
            _bus = LocalBus()
    return _bus


def set_bus(bus) -> None:
    global _bus
    _bus = bus
