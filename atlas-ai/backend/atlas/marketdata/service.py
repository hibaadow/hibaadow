"""Market data service: maintains validated candle series, quotes, 24h stats and
order-book depth for the configured universe, with staleness protection."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging import get_logger
from ..models import Candle as CandleRow
from ..models import IntegrationStatus, MarketDataRef
from .http import ProviderError
from .providers import BinanceMarketData, CoinbaseMarketData, KrakenMarketData
from .types import TF_MS, Candle, CandleSeries, Depth, MarketStats, Quote
from .validation import validate_candles
from .ws import CoinbaseTickerFeed, KrakenTickerFeed

log = get_logger("atlas.marketdata")

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
INITIAL_BARS = {"1m": 500, "5m": 500, "15m": 400, "1h": 300, "4h": 300}


@dataclass
class SymbolState:
    symbol: str
    candles: dict[str, list[Candle]] = field(default_factory=dict)
    quality: dict[str, dict] = field(default_factory=dict)
    last_fetch: dict[str, float] = field(default_factory=dict)
    quote: Quote | None = None
    ref_quotes: dict[str, Quote] = field(default_factory=dict)
    stats: MarketStats | None = None
    depth: Depth | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class Readiness:
    ok: bool
    reasons: list[str]


class MarketDataService:
    def __init__(self, symbols: list[str], use_ws: bool | None = None, primary=None):
        s = get_settings()
        self.primary = primary or BinanceMarketData()
        self.coinbase = CoinbaseMarketData()
        self.kraken = KrakenMarketData()
        self.state: dict[str, SymbolState] = {}
        self.set_symbols(symbols)
        self.use_ws = s.enable_websockets if use_ws is None else use_ws
        self.feeds = []
        self._tasks: list[asyncio.Task] = []
        self.listeners: list = []  # callables(Quote)
        self.unsupported: dict[str, str] = {}

    def set_symbols(self, symbols: list[str]) -> None:
        for sym in symbols:
            self.state.setdefault(sym, SymbolState(sym))
        for sym in list(self.state):
            if sym not in symbols:
                del self.state[sym]

    @property
    def symbols(self) -> list[str]:
        return [s for s in self.state if s not in self.unsupported]

    # ---------------- websockets -----------------
    def _on_ref_quote(self, q: Quote) -> None:
        st = self.state.get(q.symbol)
        if st is not None:
            st.ref_quotes[q.venue] = q
            for fn in self.listeners:
                try:
                    fn(q)
                except Exception:  # noqa: BLE001
                    pass

    def start_feeds(self) -> None:
        if not self.use_ws or self.feeds:
            return
        s = get_settings()
        syms = list(self.state)
        self.feeds = [CoinbaseTickerFeed(s.coinbase_ws_url, syms, self._on_ref_quote),
                      KrakenTickerFeed(s.kraken_ws_url, syms, self._on_ref_quote)]
        self._tasks = [asyncio.create_task(f.run(), name=f.name) for f in self.feeds]

    async def stop(self) -> None:
        for f in self.feeds:
            f.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.feeds, self._tasks = [], []
        for c in (self.primary.client, self.coinbase.client, self.kraken.client):
            await c.close()

    # ---------------- candles -----------------
    def _due(self, st: SymbolState, tf: str, now: float) -> bool:
        last = st.last_fetch.get(tf)
        if last is None or tf not in st.candles:
            return True
        step = TF_MS[tf] / 1000
        # refresh shortly after each bar closes, or at least every 60s for fast TFs
        return int(now // step) != int(last // step) or (tf in ("1m", "5m") and now - last > 60)

    async def refresh_candles(self, symbol: str, timeframes=TIMEFRAMES, force: bool = False) -> None:
        st = self.state[symbol]
        now = time.time()
        for tf in timeframes:
            if not force and not self._due(st, tf, now):
                continue
            try:
                if tf not in st.candles:
                    fresh = await self.primary.candles(symbol, tf, INITIAL_BARS[tf])
                    merged = fresh
                else:
                    fresh = await self.primary.candles(symbol, tf, 10)
                    by_t = {c.open_time: c for c in st.candles[tf]}
                    for c in fresh:
                        by_t[c.open_time] = c
                    merged = sorted(by_t.values(), key=lambda c: c.open_time)[-INITIAL_BARS[tf]:]
                clean, report = validate_candles(merged, tf)
                if report["missing_bars"] and tf in st.candles:
                    # attempt a targeted backfill once (recovers from transient gaps)
                    full = await self.primary.candles(symbol, tf, INITIAL_BARS[tf])
                    clean, report = validate_candles(full, tf)
                st.candles[tf] = clean
                st.quality[tf] = report
                st.last_fetch[tf] = now
            except ProviderError as e:
                if e.status == 400 and "Invalid symbol" in str(e):
                    self.unsupported[symbol] = "symbol not listed on primary venue"
                    return
                st.errors = (st.errors + [f"{tf}: {e}"])[-5:]
                if not await self._fallback(st, symbol, tf, now):
                    st.quality.setdefault(tf, {})["usable"] = False

    async def _fallback(self, st: SymbolState, symbol: str, tf: str, now: float) -> bool:
        """REST fallback: replace the WHOLE series from one fallback venue (never mix venues within a series)."""
        for prov in (self.coinbase, self.kraken):
            try:
                fresh = await prov.candles(symbol, tf, INITIAL_BARS[tf])
            except (ProviderError, KeyError, ValueError):
                continue
            clean, report = validate_candles(fresh, tf)
            if report["usable"] and len(clean) >= 100:
                report["source"] = prov.venue
                report["issues"] = report["issues"] + [f"primary venue unavailable — using {prov.venue} fallback (USD book)"]
                st.candles[tf] = clean
                st.quality[tf] = report
                st.last_fetch[tf] = now
                log.warning("candle fallback used", extra={"data": {"symbol": symbol, "tf": tf, "venue": prov.venue}})
                return True
        return False

    def series(self, symbol: str, tf: str) -> CandleSeries | None:
        st = self.state.get(symbol)
        if not st or tf not in st.candles:
            return None
        return CandleSeries.from_candles(symbol, tf, self.primary.venue, st.candles[tf], st.quality.get(tf))

    # ---------------- quotes / stats -----------------
    async def refresh_quotes(self) -> None:
        syms = self.symbols
        if not syms:
            return
        try:
            qs = await self.primary.quotes(syms)
        except ProviderError as e:
            # Fallback: fresh WebSocket reference quotes (Coinbase/Kraken USD books), clearly tagged by venue.
            log.warning("primary quote refresh failed; using reference feeds", extra={"data": {"error": str(e)}})
            qs = {}
            for sym in syms:
                refs = sorted((q for q in self.state[sym].ref_quotes.values() if q.age() < 10), key=lambda q: q.age())
                if refs:
                    qs[sym] = refs[0]
        for sym, q in qs.items():
            if sym in self.state:
                self.state[sym].quote = q
                for fn in self.listeners:
                    try:
                        fn(q)
                    except Exception:  # noqa: BLE001
                        pass

    async def refresh_stats(self) -> None:
        syms = self.symbols
        if not syms:
            return
        try:
            stats = await self.primary.stats_24h(syms)
        except ProviderError as e:
            if e.status == 400:
                # one bad symbol poisons the batch: fall back to per-symbol calls
                stats = {}
                for s in syms:
                    try:
                        stats.update(await self.primary.stats_24h([s]))
                    except ProviderError:
                        self.unsupported[s] = "symbol not listed on primary venue"
            else:
                return
        for sym, st in stats.items():
            if sym in self.state:
                self.state[sym].stats = st

    async def refresh_depth(self, symbol: str) -> None:
        try:
            self.state[symbol].depth = await self.primary.depth(symbol)
        except ProviderError as e:
            self.state[symbol].errors = (self.state[symbol].errors + [f"depth: {e}"])[-5:]

    # ---------------- safety -----------------
    def readiness(self, symbol: str, tfs: tuple[str, ...], max_quote_age: float, max_divergence_pct: float) -> Readiness:
        """Is the data for ``symbol`` complete and fresh enough to trade on?"""
        st = self.state.get(symbol)
        reasons: list[str] = []
        if st is None or symbol in self.unsupported:
            return Readiness(False, [self.unsupported.get(symbol, "unknown symbol")])
        for tf in tfs:
            q = st.quality.get(tf)
            if not q:
                reasons.append(f"{tf} candles not loaded")
            elif not q.get("usable"):
                reasons.append(f"{tf} candles unusable: {', '.join(q.get('issues') or ['fetch failed'])}")
        if st.quote is None:
            reasons.append("no top-of-book quote")
        elif st.quote.age() > max_quote_age:
            reasons.append(f"quote is stale ({st.quote.age():.0f}s old)")
        if st.quote is not None:
            refs = [r for r in st.ref_quotes.values() if r.age() < 120]
            for r in refs:
                div = abs(r.mid / st.quote.mid - 1) * 100
                # USD vs USDC books can differ slightly; large divergence = suspect data
                if div > max_divergence_pct:
                    reasons.append(f"price diverges {div:.2f}% from {r.venue} reference — possible bad data")
        return Readiness(not reasons, reasons)

    # ---------------- persistence -----------------
    def persist(self, db: Session, symbol: str) -> None:
        st = self.state.get(symbol)
        if not st:
            return
        venue = self.primary.venue
        for tf, candles in st.candles.items():
            tail = candles[-50:]
            if tail and db.bind is not None and db.bind.dialect.name == "postgresql":
                stmt = pg_insert(CandleRow).values([
                    dict(venue=venue, symbol=symbol, timeframe=tf, open_time=c.open_time, open=c.open, high=c.high,
                         low=c.low, close=c.close, volume=c.volume, quote_volume=c.quote_volume) for c in tail])
                stmt = stmt.on_conflict_do_update(index_elements=["venue", "symbol", "timeframe", "open_time"],
                                                  set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "quote_volume")})
                db.execute(stmt)
            q = st.quality.get(tf, {})
            ref = db.query(MarketDataRef).filter_by(venue=venue, symbol=symbol, timeframe=tf).one_or_none()
            if ref is None:
                ref = MarketDataRef(venue=venue, symbol=symbol, timeframe=tf)
                db.add(ref)
            ref.first_open_time = candles[0].open_time if candles else None
            ref.last_open_time = candles[-1].open_time if candles else None
            ref.candle_count = len(candles)
            ref.gaps = q.get("missing_bars", 0)
            ref.duplicates = q.get("duplicates", 0)
            ref.invalid = q.get("invalid", 0)
            ref.status = "ok" if q.get("usable") else ("stale" if q.get("stale") else "degraded")
            ref.last_validated = datetime.now(timezone.utc)

    def integration_health(self) -> dict[str, dict]:
        out = {
            "binance_rest": self.primary.client.health(),
            "coinbase_rest": self.coinbase.client.health(),
            "kraken_rest": self.kraken.client.health(),
        }
        for f in self.feeds:
            out[f.name] = f.health()
        return out

    def write_integration_status(self, db: Session) -> None:
        for name, h in self.integration_health().items():
            row = db.get(IntegrationStatus, name) or IntegrationStatus(name=name)
            row.status = h.get("status", "unknown")
            row.last_error = h.get("last_error")
            row.latency_ms = h.get("latency_ms")
            if h.get("last_ok") or h.get("last_message"):
                row.last_ok = datetime.fromtimestamp(h.get("last_ok") or h.get("last_message"), timezone.utc)
            row.details = {k: v for k, v in h.items() if k in ("reconnects",)}
            db.merge(row)
