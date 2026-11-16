"""Deterministic position-management rules (pure; shared by paper, broker and backtest execution).

For BUY positions prices are evaluated on the BID (where a long is closed); for SELL positions on the ASK.
1. Mandatory protective stop. Within a bar the stop is evaluated before any target (conservative).
2. At +1R the stop moves to breakeven (entry ± round-trip costs).
3. TP1 (≥ 2R net): close 50 %, stop moves to +1R.  4. TP2: close the rest.
5. Time stops: no progress to +0.5R within ``stale_after_s``; hard max holding time (day trading).
"""
from __future__ import annotations

from dataclasses import dataclass, field

TRADE_THROUGH = 0.0  # extra distance (price units) required beyond a target; set per instrument by callers


@dataclass
class PosState:
    entry: float
    qty: float
    initial_qty: float
    stop: float
    initial_stop: float
    tp1: float
    tp2: float | None
    opened_ts: float
    side: str = "buy"
    tp1_hit: bool = False
    best: float | None = None  # most favourable price seen
    breakeven_set: bool = False
    cost_per_unit: float = 0.0  # round-trip costs in price units (for true breakeven)
    through: float = 0.0  # trade-through requirement for limit targets (price units)

    @property
    def sign(self) -> int:
        return 1 if self.side == "buy" else -1

    @property
    def r(self) -> float:
        return (self.entry - self.initial_stop) * self.sign


@dataclass
class Action:
    kind: str  # stop | tp1 | tp2 | move_stop | time_exit
    price: float
    fraction: float = 0.0
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class RuleParams:
    tp1_fraction: float = 0.5
    breakeven_at_r: float = 1.0
    stale_after_s: float = 3 * 3600
    stale_min_r: float = 0.5
    max_hold_s: float = 20 * 3600


def manage(st: PosState, low: float, high: float, close: float, now_ts: float, p: RuleParams | None = None,
           open_: float | None = None) -> list[Action]:
    """``low``/``high``/``close``/``open_`` are prices on the side that CLOSES the position."""
    p = p or RuleParams()
    acts: list[Action] = []
    if st.qty <= 0:
        return acts
    sg = st.sign
    adverse, favourable = (low, high) if sg == 1 else (high, low)
    if sg * (adverse - st.stop) <= 0:  # stop touched
        gap = open_ is not None and sg * (open_ - st.stop) < 0
        acts.append(Action("stop", open_ if gap else st.stop, 1.0, f"protective stop {st.stop:.6g} hit"))
        return acts
    st.best = favourable if st.best is None else (max(st.best, favourable) if sg == 1 else min(st.best, favourable))
    r = st.r
    hit = lambda tgt: sg * (favourable - tgt) >= st.through  # noqa: E731
    if not st.tp1_hit and hit(st.tp1):
        acts.append(Action("tp1", st.tp1, p.tp1_fraction if st.tp2 else 1.0, f"take-profit 1 at {st.tp1:.6g} ({sg * (st.tp1 - st.entry) / r:.1f}R)"))
        new_stop = st.entry + sg * r
        if st.tp2 and sg * (new_stop - st.stop) > 0:
            acts.append(Action("move_stop", new_stop, 0, f"TP1 filled — stop moved to +1R ({new_stop:.6g})"))
        if st.tp2 and hit(st.tp2):
            acts.append(Action("tp2", st.tp2, 1.0, f"take-profit 2 at {st.tp2:.6g}"))
        return acts
    if st.tp1_hit and st.tp2 and hit(st.tp2):
        return [Action("tp2", st.tp2, 1.0, f"take-profit 2 at {st.tp2:.6g} ({sg * (st.tp2 - st.entry) / r:.1f}R)")]
    if not st.breakeven_set and r > 0 and sg * (st.best - st.entry) >= p.breakeven_at_r * r:
        be = st.entry + sg * st.cost_per_unit
        if sg * (be - st.stop) > 0:
            acts.append(Action("move_stop", be, 0, f"+{p.breakeven_at_r:g}R reached — stop to breakeven ({be:.6g})", {"breakeven": True}))
    age = now_ts - st.opened_ts
    if age >= p.max_hold_s:
        acts.append(Action("time_exit", close, 1.0, f"maximum holding time {p.max_hold_s / 3600:.0f}h reached"))
    elif age >= p.stale_after_s and not st.tp1_hit and sg * (st.best - st.entry) < p.stale_min_r * r:
        acts.append(Action("time_exit", close, 1.0, f"no progress to +{p.stale_min_r}R after {p.stale_after_s / 3600:.0f}h — time stop"))
    return acts


def apply(st: PosState, act: Action, filled_qty: float | None = None) -> None:
    if act.kind == "move_stop":
        st.stop = act.price if st.sign * (act.price - st.stop) > 0 else st.stop
        if act.meta.get("breakeven"):
            st.breakeven_set = True
        return
    sold = filled_qty if filled_qty is not None else st.qty * act.fraction
    st.qty = max(0.0, round(st.qty - sold, 8))
    if act.kind == "tp1":
        st.tp1_hit = True
        st.breakeven_set = True
