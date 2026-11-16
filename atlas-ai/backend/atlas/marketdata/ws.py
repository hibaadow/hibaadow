"""WebSocket reference-price feeds with automatic reconnection.

Binance's public WebSocket endpoint is geo-restricted from some regions, so live
reference ticks come from Coinbase Exchange and Kraken (both public, keyless).
They are used to (1) detect stale/manipulated primary-venue data via
cross-venue divergence checks and (2) provide sub-second price updates to the UI.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Callable

import websockets

from ..logging import get_logger
from .providers import split_symbol
from .types import Quote

log = get_logger("atlas.ws")

OnQuote = Callable[[Quote], None]


class ReconnectingFeed:
    name = "feed"

    def __init__(self, url: str, symbols: list[str], on_quote: OnQuote):
        self.url = url
        self.symbols = symbols
        self.on_quote = on_quote
        self.connected = False
        self.last_message: float | None = None
        self.reconnects = 0
        self.last_error: str | None = None
        self._stop = asyncio.Event()

    def subscribe_message(self) -> dict:
        raise NotImplementedError

    def parse(self, msg: dict) -> list[Quote]:
        raise NotImplementedError

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=10, ping_interval=20, ping_timeout=20,
                                              max_size=2**20) as ws:
                    await ws.send(json.dumps(self.subscribe_message()))
                    self.connected = True
                    backoff = 1.0
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        self.last_message = time.time()
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        for q in self.parse(msg):
                            if q.bid > 0 and q.ask >= q.bid:
                                self.on_quote(q)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — any failure triggers reconnect
                self.last_error = f"{type(e).__name__}: {str(e)[:120]}"
                log.warning("ws feed disconnected", extra={"data": {"feed": self.name, "error": self.last_error}})
            self.connected = False
            self.reconnects += 1
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)

    def stop(self) -> None:
        self._stop.set()

    def health(self) -> dict:
        fresh = self.last_message is not None and time.time() - self.last_message < 90
        return {"status": "ok" if self.connected and fresh else ("degraded" if self.connected else "down"),
                "reconnects": self.reconnects, "last_error": self.last_error, "last_message": self.last_message}


class CoinbaseTickerFeed(ReconnectingFeed):
    name = "coinbase_ws"

    def __init__(self, url, symbols, on_quote):
        super().__init__(url, symbols, on_quote)
        self._map = {f"{split_symbol(s)[0]}-USD": s for s in symbols}

    def subscribe_message(self) -> dict:
        return {"type": "subscribe", "product_ids": list(self._map), "channels": ["ticker"]}

    def parse(self, msg: dict) -> list[Quote]:
        if msg.get("type") != "ticker" or msg.get("product_id") not in self._map:
            return []
        try:
            return [Quote(self._map[msg["product_id"]], "coinbase", float(msg["best_bid"]), float(msg["best_ask"]), float(msg["price"]))]
        except (KeyError, ValueError, TypeError):
            return []


class KrakenTickerFeed(ReconnectingFeed):
    name = "kraken_ws"
    ALIASES = {"BTC": "BTC"}  # Kraken v2 uses BTC/USD

    def __init__(self, url, symbols, on_quote):
        super().__init__(url, symbols, on_quote)
        self._map = {f"{split_symbol(s)[0]}/USD": s for s in symbols}

    def subscribe_message(self) -> dict:
        return {"method": "subscribe", "params": {"channel": "ticker", "symbol": list(self._map)}}

    def parse(self, msg: dict) -> list[Quote]:
        if msg.get("channel") != "ticker":
            return []
        out = []
        for row in msg.get("data", []) or []:
            sym = self._map.get(row.get("symbol"))
            if not sym:
                continue
            try:
                out.append(Quote(sym, "kraken", float(row["bid"]), float(row["ask"]), float(row["last"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out
