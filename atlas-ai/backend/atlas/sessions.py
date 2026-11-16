"""Trading sessions and market hours (DST-aware via IANA time zones).

* FX trades 24/5: from Sunday 17:00 New York time to Friday 17:00 New York time.
* Spot gold follows the same week with a daily maintenance break 17:00–18:00 New York time.
* The daily rollover (≈17:00 New York) has wide spreads; new entries are avoided ±10 min around it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
LDN = ZoneInfo("Europe/London")
TKY = ZoneInfo("Asia/Tokyo")
SYD = ZoneInfo("Australia/Sydney")

SESSIONS = {  # local opening hours
    "Sydney": (SYD, time(7), time(16)),
    "Tokyo": (TKY, time(9), time(18)),
    "London": (LDN, time(8), time(17)),
    "New York": (NY, time(8), time(17)),
}


def _in(local: datetime, start: time, end: time) -> bool:
    return start <= local.time() < end


def active_sessions(ts: datetime) -> list[str]:
    ts = ts.astimezone(timezone.utc)
    return [name for name, (tz, a, b) in SESSIONS.items() if ts.astimezone(tz).weekday() < 5 and _in(ts.astimezone(tz), a, b)]


def is_market_open(ts: datetime, asset_class: str = "forex") -> bool:
    ny = ts.astimezone(NY)
    wd, t = ny.weekday(), ny.time()
    if wd == 5:  # Saturday
        return False
    if wd == 6 and t < time(17):  # Sunday before open
        return False
    if wd == 4 and t >= time(17):  # Friday after close
        return False
    if asset_class == "gold" and time(17) <= t < time(18):
        return False
    return True


def near_rollover(ts: datetime, minutes: int = 10) -> bool:
    ny = ts.astimezone(NY)
    roll = ny.replace(hour=17, minute=0, second=0, microsecond=0)
    return abs((ny - roll).total_seconds()) <= minutes * 60


@dataclass
class SessionInfo:
    active: list[str]
    overlap_london_ny: bool
    label: str
    quality: float  # 0..1 liquidity/participation heuristic for the instrument
    market_open: bool
    rollover: bool


QUALITY = {  # which sessions matter for each currency
    "USD": ("London", "New York"), "EUR": ("London", "New York"), "GBP": ("London", "New York"), "CHF": ("London", "New York"),
    "CAD": ("New York",), "JPY": ("Tokyo", "London", "New York"), "AUD": ("Sydney", "Tokyo", "London"),
    "NZD": ("Sydney", "Tokyo"), "XAU": ("London", "New York"),
}


def session_info(ts: datetime, currencies: tuple[str, ...], asset_class: str) -> SessionInfo:
    act = active_sessions(ts)
    overlap = "London" in act and "New York" in act
    relevant = set()
    for c in currencies:
        relevant.update(QUALITY.get(c, ("London", "New York")))
    hits = len(relevant & set(act))
    q = 1.0 if overlap and ({"London", "New York"} <= relevant) else min(1.0, 0.25 + 0.4 * hits)
    if not act:
        q = 0.1
    label = "London/NY overlap" if overlap else (" + ".join(act) if act else "Off-session")
    return SessionInfo(act, overlap, label, round(q, 2), is_market_open(ts, asset_class), near_rollover(ts))


def session_window_utc(day: datetime, name: str) -> tuple[datetime, datetime]:
    """UTC start/end of a named session on the local calendar day containing ``day``."""
    tz, a, b = SESSIONS[name]
    local = day.astimezone(tz)
    start = datetime.combine(local.date(), a, tz)
    end = datetime.combine(local.date(), b, tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def expected_closed(t_ms: int, step_ms: int, asset_class: str) -> bool:
    """True if a bar starting at t_ms falls entirely in a market closure (not a data gap)."""
    t = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
    return not is_market_open(t, asset_class) and not is_market_open(t + timedelta(milliseconds=step_ms - 1), asset_class)
