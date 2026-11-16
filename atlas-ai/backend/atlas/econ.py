"""Economic calendar, central-bank events, US Treasury yields and currency strength.

Sources (public, keyless):
* Economic calendar — ForexFactory weekly JSON export (nfs.faireconomy.media). Fetched at most every 30 min.
* US 10-year Treasury yield — FRED series DGS10 (daily, published with ~1 day lag).
* Currency strength / USD strength — computed from the tracked FX pairs' own price changes
  (no external index is fabricated; it is clearly labelled as derived).
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import get_settings
from .instruments import FOREX, INSTRUMENTS
from .logging import get_logger
from .marketdata.http import ProviderClient, ProviderError

log = get_logger("atlas.econ")

CENTRAL_BANK_KEYWORDS = ("federal funds rate", "fomc", "main refinancing rate", "monetary policy", "official bank rate", "boj policy rate",
                         "cash rate", "overnight rate", "snb policy rate", "rate statement", "policy rate", "press conference",
                         "interest rate decision", "monetary policy statement", "fed chair", "ecb president", "boe gov", "gov ", "governor",
                         "fomc member", "mpc member")
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")


@dataclass
class EconEvent:
    title: str
    currency: str
    time: datetime
    impact: str  # High | Medium | Low | Holiday
    forecast: str = ""
    previous: str = ""
    central_bank: bool = False

    def to_dict(self) -> dict:
        return {"title": self.title, "currency": self.currency, "time": self.time.isoformat(), "impact": self.impact,
                "forecast": self.forecast, "previous": self.previous, "central_bank": self.central_bank}


def parse_calendar(rows) -> list[EconEvent]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            cur = str(r.get("country", "")).upper()[:3]
            if cur not in CURRENCIES and cur != "ALL":
                continue
            t = datetime.fromisoformat(str(r["date"])).astimezone(timezone.utc)
            title = str(r.get("title", ""))[:120]
            impact = str(r.get("impact", "Low"))
            if impact not in ("High", "Medium", "Low", "Holiday", "Non-Economic"):
                impact = "Low"
            out.append(EconEvent(title, cur, t, impact, str(r.get("forecast", ""))[:24], str(r.get("previous", ""))[:24],
                                 any(k in title.lower() for k in CENTRAL_BANK_KEYWORDS)))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda e: e.time)


def relevant_currencies(symbol: str) -> tuple[str, ...]:
    inst = INSTRUMENTS[symbol]
    return ("USD",) if inst.asset_class == "gold" else (inst.base, inst.quote)


def blackout(events: list[EconEvent], symbol: str, now: datetime, before_min: int, after_min: int, cb_extra_min: int = 30) -> EconEvent | None:
    """High-impact event for the instrument's currencies within the no-trade window, if any."""
    cur = relevant_currencies(symbol)
    for e in events:
        if e.impact != "High" or (e.currency not in cur and e.currency != "ALL"):
            continue
        extra = cb_extra_min if e.central_bank else 0
        if e.time - timedelta(minutes=before_min + extra) <= now <= e.time + timedelta(minutes=after_min + extra):
            return e
    return None


def upcoming(events: list[EconEvent], symbol: str | None, now: datetime, hours: int = 24, min_impact: str = "Medium") -> list[EconEvent]:
    order = {"Low": 0, "Medium": 1, "High": 2}
    cur = relevant_currencies(symbol) if symbol else CURRENCIES
    return [e for e in events if now - timedelta(minutes=30) <= e.time <= now + timedelta(hours=hours)
            and e.currency in cur and order.get(e.impact, -1) >= order[min_impact]]


class EconService:
    def __init__(self):
        s = get_settings()
        self.ff = ProviderClient("forexfactory_calendar", s.calendar_url, rate_per_sec=0.05, burst=1, max_retries=1)
        self.fred = ProviderClient("fred", "https://fred.stlouisfed.org", rate_per_sec=0.2, burst=1, max_retries=1)
        self.events: list[EconEvent] = []
        self.events_fetched: float | None = None
        self.us10y: dict | None = None
        self.us10y_fetched: float | None = None

    async def refresh(self, force: bool = False) -> None:
        now = time.time()
        if force or not self.events_fetched or now - self.events_fetched > 1800:
            try:
                rows = await self.ff.get("/ff_calendar_thisweek.json")
                ev = parse_calendar(rows)
                if ev:
                    self.events = ev
                self.events_fetched = now
            except ProviderError as e:
                log.warning("calendar fetch failed", extra={"data": {"error": str(e)[:160]}})
        if force or not self.us10y_fetched or now - self.us10y_fetched > 6 * 3600:
            try:
                self.us10y = await self.fetch_us10y()
                self.us10y_fetched = now
            except (ProviderError, ValueError) as e:
                log.warning("FRED fetch failed", extra={"data": {"error": str(e)[:160]}})

    async def fetch_us10y(self) -> dict:
        start = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        text = await self.fred.get_text("/graph/fredgraph.csv", id="DGS10", cosd=start)
        rows = [r for r in csv.reader(io.StringIO(text))][1:]
        vals = [(d, float(v)) for d, v in rows if v not in ("", ".")]
        if len(vals) < 6:
            raise ValueError("insufficient FRED data")
        last_d, last = vals[-1]
        prev5 = vals[-6][1]
        return {"series": "DGS10", "source": "FRED (daily close)", "date": last_d, "value": last, "change_5d_bp": round((last - prev5) * 100, 1),
                "trend": "rising" if last - prev5 > 0.05 else ("falling" if last - prev5 < -0.05 else "flat"),
                "history": [{"date": d, "value": v} for d, v in vals[-30:]]}

    async def close(self):
        await self.ff.close()
        await self.fred.close()


def currency_strength(closes: dict[str, np.ndarray], lookback: int) -> dict[str, float]:
    """Average % change of each currency vs the others over ``lookback`` bars (derived from tracked FX pairs)."""
    scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}
    for sym in FOREX:
        c = closes.get(sym)
        if c is None or len(c) <= lookback:
            continue
        chg = (c[-1] / c[-1 - lookback] - 1) * 100
        inst = INSTRUMENTS[sym]
        scores[inst.base].append(chg)
        scores[inst.quote].append(-chg)
    return {k: round(float(np.mean(v)), 4) for k, v in scores.items() if v}


@dataclass
class MacroSnapshot:
    strength: dict[str, float] = field(default_factory=dict)
    us10y: dict | None = None
    events: list[EconEvent] = field(default_factory=list)

    @property
    def usd(self) -> float | None:
        return self.strength.get("USD")
