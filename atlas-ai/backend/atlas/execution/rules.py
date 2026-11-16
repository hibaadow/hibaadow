"""Deterministic position-management rules (pure; shared by paper trading and the backtester).

1. Mandatory protective stop from entry.
2. Once price reaches +1R, the stop moves to breakeven (entry + round-trip fees).
3. TP1 at the first target (>= 2R): sell 50%, stop moves to +1R.
4. TP2 at the second target: sell the remainder.
5. Strategy exit signal: exit the remainder at market.
6. Time stop: day-trading positions that have not reached +0.5R within
   ``stale_after_s`` are closed; every position is closed after ``max_hold_s``.

Within a single bar the stop is evaluated before any target (conservative).
"""
from __future__ import annotations

from dataclasses import dataclass, field


TRADE_THROUGH = 1.0001  # limit targets only fill when price trades 1bp through them


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
    tp1_hit: bool = False
    high_water: float = 0.0
    breakeven_set: bool = False
    fee_per_unit: float = 0.0  # round-trip fees per unit, used for true breakeven

    @property
    def r(self) -> float:
        return self.entry - self.initial_stop


@dataclass
class Action:
    kind: str  # stop | tp1 | tp2 | move_stop | time_exit
    price: float
    fraction: float = 0.0  # fraction of CURRENT qty to sell
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class RuleParams:
    tp1_fraction: float = 0.5
    breakeven_at_r: float = 1.0
    stale_after_s: float = 4 * 3600
    stale_min_r: float = 0.5
    max_hold_s: float = 24 * 3600


def manage(st: PosState, low: float, high: float, close: float, now_ts: float, p: RuleParams | None = None,
           open_: float | None = None) -> list[Action]:
    p = p or RuleParams()
    acts: list[Action] = []
    if st.qty <= 0:
        return acts
    # 1) stop first — if the bar traded through the stop, assume it was hit before any target
    if low <= st.stop:
        # gap through the stop → fill at the (worse) open; otherwise at the stop level
        fill = open_ if open_ is not None and open_ < st.stop else st.stop
        acts.append(Action("stop", fill, 1.0, f"protective stop {st.stop:.8g} hit (low {low:.8g})"))
        return acts
    st.high_water = max(st.high_water, high)
    r = st.r
    # 2) targets
    if not st.tp1_hit and high >= st.tp1 * TRADE_THROUGH:
        frac = p.tp1_fraction if st.tp2 else 1.0
        acts.append(Action("tp1", st.tp1, frac, f"take-profit 1 at {st.tp1:.8g} ({(st.tp1 - st.entry) / r:.1f}R)"))
        new_stop = st.entry + r * 1.0
        if st.tp2 and new_stop > st.stop:
            acts.append(Action("move_stop", new_stop, 0, f"TP1 filled — stop raised to +1R ({new_stop:.8g})"))
        if st.tp2 and high >= st.tp2 * TRADE_THROUGH:
            acts.append(Action("tp2", st.tp2, 1.0, f"take-profit 2 at {st.tp2:.8g} ({(st.tp2 - st.entry) / r:.1f}R)"))
        return acts
    if st.tp1_hit and st.tp2 and high >= st.tp2 * TRADE_THROUGH:
        acts.append(Action("tp2", st.tp2, 1.0, f"take-profit 2 at {st.tp2:.8g} ({(st.tp2 - st.entry) / r:.1f}R)"))
        return acts
    # 3) breakeven
    if not st.breakeven_set and r > 0 and st.high_water >= st.entry + p.breakeven_at_r * r:
        be = st.entry + st.fee_per_unit
        if be > st.stop:
            acts.append(Action("move_stop", be, 0, f"price reached +{p.breakeven_at_r:g}R — stop moved to breakeven ({be:.8g})",
                               {"breakeven": True}))
    # 4) time stops
    age = now_ts - st.opened_ts
    if age >= p.max_hold_s:
        acts.append(Action("time_exit", close, 1.0, f"maximum holding time {p.max_hold_s / 3600:.0f}h reached"))
    elif age >= p.stale_after_s and not st.tp1_hit and st.high_water < st.entry + p.stale_min_r * r:
        acts.append(Action("time_exit", close, 1.0, f"no progress to +{p.stale_min_r}R after {p.stale_after_s / 3600:.0f}h — time stop"))
    return acts


def apply(st: PosState, act: Action, filled_qty: float | None = None) -> None:
    """Mutate state after an action is executed."""
    if act.kind == "move_stop":
        st.stop = max(st.stop, act.price)
        if act.meta.get("breakeven"):
            st.breakeven_set = True
        return
    sold = filled_qty if filled_qty is not None else st.qty * act.fraction
    st.qty = max(0.0, st.qty - sold)
    if act.kind == "tp1":
        st.tp1_hit = True
        st.breakeven_set = True
