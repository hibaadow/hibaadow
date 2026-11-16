"""Market data service for gold & forex: validated candles, live quotes, readiness checks.

Sources (``ATLAS_DATA_SOURCE``):
* ``oanda`` / ``mt5``  — broker candles (bid/ask) and live prices.
* ``public``           — Swissquote public quotes with locally-built bars (see brokers/public.py).
When a broker is the source, the public quote feed is also polled as an independent reference to
detect stale or manipulated prices (cross-source divergence check).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..brokers.public import PublicSource
from ..instruments import CONVERSION_PAIRS, INSTRUMENTS
from ..logging import get_logger
from ..marketdata.http import ProviderError
from ..models import Candle as CandleRow
from ..models import IntegrationStatus, MarketDataRef
from ..sessions import is_market_open
from .types import TF_MS, Candle, CandleSeries, Quote
from .validation import validate_candles

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
    ref_quote: Quote | None = None
    spread_history: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Readiness:
    ok: bool
    reasons: list[str]


class MarketDataService:
    def __init__(self, symbols: list[str], source=None, reference: PublicSource | None = None):
        self.source = source or PublicSource()
        self.reference = reference  # independent quote feed when trading from broker data
        self.state: dict[str, SymbolState] = {}
        self.listeners: list = []
        self._persisted_upto: dict[tuple[str, str], int] = {}
        self.set_symbols(symbols)

    @property
    def venue(self) -> str:
        return self.source.name

    def set_symbols(self, symbols: list[str]) -> None:
        wanted = set(symbols) | set(CONVERSION_PAIRS.values())  # conversion pairs always quoted (pip values)
        for s in wanted:
            self.state.setdefault(s, SymbolState(s))
        for s in list(self.state):
            if s not in wanted:
                del self.state[s]
        self.traded = [s for s in symbols if s in INSTRUMENTS]

    @property
    def symbols(self) -> list[str]:
        return list(self.state)

    # ------------------------------------------------------------- quotes
    async def refresh_quotes(self) -> None:
        try:
            qs = await self.source.quotes(self.symbols)
        except ProviderError as e:
            log.warning("quote refresh failed", extra={"data": {"error": str(e)[:160]}})
            qs = {}
        for sym, q in qs.items():
            st = self.state.get(sym)
            if st is None:
                continue
            st.quote = q
            st.spread_history = (st.spread_history + [q.ask - q.bid])[-500:]
            for fn in self.listeners:
                try:
                    fn(q)
                except Exception:  # noqa: BLE001
                    pass

    async def refresh_reference(self) -> None:
        if self.reference is None:
            return
        try:
            for sym, q in (await self.reference.quotes(self.traded)).items():
                self.state[sym].ref_quote = q
        except ProviderError:
            pass

    def mids(self) -> dict[str, float]:
        return {s: st.quote.mid for s, st in self.state.items() if st.quote}

    # ------------------------------------------------------------- candles
    def _due(self, st: SymbolState, tf: str, now: float) -> bool:
        last = st.last_fetch.get(tf)
        if last is None or tf not in st.candles:
            return True
        step = TF_MS[tf] / 1000
        return int(now // step) != int(last // step) or now - last > 60

    async def refresh_candles(self, symbol: str, timeframes=TIMEFRAMES, force: bool = False) -> None:
        st = self.state[symbol]
        inst = INSTRUMENTS[symbol]
        now = time.time()
        for tf in timeframes:
            if not force and not self._due(st, tf, now):
                continue
            try:
                need = INITIAL_BARS[tf] if tf not in st.candles else 20
                fresh = await self.source.candles(symbol, tf, need)
                if tf in st.candles and self.source.name != "public":
                    by_t = {c.open_time: c for c in st.candles[tf]}
                    by_t.update({c.open_time: c for c in fresh})
                    fresh = sorted(by_t.values(), key=lambda c: c.open_time)[-INITIAL_BARS[tf]:]
                clean, report = validate_candles(fresh, tf, asset_class=inst.asset_class, drop_open=True)
                report["source"] = self.source.name
                if self.source.name == "public":
                    report["note"] = "bars built from sampled public quotes"
                st.candles[tf] = clean
                st.quality[tf] = report
                st.last_fetch[tf] = now
            except ProviderError as e:
                st.errors = (st.errors + [f"{tf}: {e}"])[-5:]
                st.quality.setdefault(tf, {})["usable"] = False

    def series(self, symbol: str, tf: str) -> CandleSeries | None:
        st = self.state.get(symbol)
        if not st or tf not in st.candles:
            return None
        return CandleSeries.from_candles(symbol, tf, self.source.name, st.candles[tf], st.quality.get(tf))

    def typical_spread(self, symbol: str) -> float | None:
        h = self.state[symbol].spread_history
        if not h:
            return None
        s = sorted(h)
        return s[len(s) // 2]

    # ------------------------------------------------------------- safety
    def readiness(self, symbol: str, tfs: tuple[str, ...], max_quote_age: float, max_divergence_pips: float = 15.0,
                  min_bars: int = 150, now: datetime | None = None) -> Readiness:
        st = self.state.get(symbol)
        if st is None or symbol not in INSTRUMENTS:
            return Readiness(False, ["unsupported instrument"])
        inst = INSTRUMENTS[symbol]
        reasons: list[str] = []
        if not is_market_open(now or datetime.now(timezone.utc), inst.asset_class):
            reasons.append("market closed")
        for tf in tfs:
            q = st.quality.get(tf)
            n = len(st.candles.get(tf, []))
            if not q:
                reasons.append(f"{tf} candles not loaded")
            elif not q.get("usable"):
                if self.source.name == "public" and n == 0:
                    reasons.append(f"{tf}: building bars from the public quote feed (no history yet — connect OANDA/MT5 for instant history)")
                else:
                    reasons.append(f"{tf} candles unusable: {', '.join(q.get('issues') or ['fetch failed'])}")
            elif n < min_bars and tf in tfs[:1]:
                reasons.append(f"{tf}: only {n} closed bars (need {min_bars}) — still accumulating history")
        if st.quote is None:
            reasons.append("no live quote")
        elif st.quote.age() > max_quote_age:
            reasons.append(f"quote is stale ({st.quote.age():.0f}s old)")
        if st.quote is not None and st.ref_quote is not None and st.ref_quote.age() < 60:
            div = inst.to_pips(abs(st.ref_quote.mid - st.quote.mid))
            if div > max_divergence_pips:
                reasons.append(f"price differs {div:.1f} pips from independent reference — possible bad data")
        return Readiness(not reasons, reasons)

    # ------------------------------------------------------------- persistence
    def persist(self, db: Session, symbol: str) -> None:
        st = self.state.get(symbol)
        if not st:
            return
        venue = self.source.name
        for tf, candles in st.candles.items():
            key = (symbol, tf)
            upto = self._persisted_upto.get(key, 0)
            rows = [c for c in candles if c.open_time > upto]
            if rows and db.bind is not None and db.bind.dialect.name == "postgresql":
                stmt = pg_insert(CandleRow).values([dict(venue=venue, symbol=symbol, timeframe=tf, open_time=c.open_time, open=c.open, high=c.high,
                                                          low=c.low, close=c.close, volume=c.volume, quote_volume=0.0, spread=c.spread) for c in rows[-1000:]])
                stmt = stmt.on_conflict_do_update(index_elements=["venue", "symbol", "timeframe", "open_time"],
                                                  set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "spread")})
                db.execute(stmt)
                self._persisted_upto[key] = rows[-1].open_time
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

    def persist_public_bars(self, db: Session) -> int:
        """Store completed 1-minute bars built from public quotes so history survives restarts."""
        if not isinstance(self.source, PublicSource):
            return 0
        done = self.source.builder.completed
        self.source.builder.completed = []
        if not done or db.bind is None or db.bind.dialect.name != "postgresql":
            return 0
        stmt = pg_insert(CandleRow).values([dict(venue="public", symbol=s, timeframe="1m", open_time=c.open_time, open=c.open, high=c.high,
                                                 low=c.low, close=c.close, volume=c.volume, quote_volume=0.0, spread=c.spread) for s, c in done])
        db.execute(stmt.on_conflict_do_nothing(index_elements=["venue", "symbol", "timeframe", "open_time"]))
        return len(done)

    def load_public_history(self, db: Session, days: int = 5) -> int:
        if not isinstance(self.source, PublicSource):
            return 0
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        n = 0
        for sym in self.state:
            rows = db.execute(select(CandleRow).where(CandleRow.venue == "public", CandleRow.symbol == sym, CandleRow.timeframe == "1m",
                                                      CandleRow.open_time >= since).order_by(CandleRow.open_time)).scalars().all()
            self.source.builder.load(sym, [Candle(r.open_time, r.open, r.high, r.low, r.close, r.volume, 0.0, r.spread or 0.0) for r in rows])
            n += len(rows)
        return n

    def integration_health(self) -> dict[str, dict]:
        out = dict(self.source.health())
        if self.reference is not None:
            out.update(self.reference.health())
        return out

    def write_integration_status(self, db: Session, extra: dict[str, dict] | None = None) -> None:
        for name, h in {**self.integration_health(), **(extra or {})}.items():
            row = db.get(IntegrationStatus, name) or IntegrationStatus(name=name)
            row.status = h.get("status", "unknown")
            row.last_error = h.get("last_error") or h.get("detail")
            row.latency_ms = h.get("latency_ms")
            if h.get("last_ok"):
                row.last_ok = datetime.fromtimestamp(h["last_ok"], timezone.utc)
            db.merge(row)

    async def stop(self) -> None:
        await self.source.close()
        if self.reference is not None:
            await self.reference.close()
