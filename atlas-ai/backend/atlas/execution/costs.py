"""Transaction-cost model for gold & forex: spread + commission + slippage, in account currency (USD)."""
from __future__ import annotations

from dataclasses import dataclass

from ..instruments import Instrument, pip_value_usd
from ..trading_config import CostModel


@dataclass
class CostEstimate:
    spread_usd: float
    commission_usd: float
    slippage_usd: float
    spread_pips: float
    slippage_pips: float

    @property
    def total_usd(self) -> float:
        return self.spread_usd + self.commission_usd + self.slippage_usd

    def to_dict(self) -> dict:
        return {"spread_usd": round(self.spread_usd, 2), "commission_usd": round(self.commission_usd, 2), "slippage_usd": round(self.slippage_usd, 2),
                "total_usd": round(self.total_usd, 2), "spread_pips": round(self.spread_pips, 2), "slippage_pips": round(self.slippage_pips, 2)}


def commission_per_side(inst: Instrument, lots: float, cm: CostModel) -> float:
    rate = cm.gold_commission_per_lot_side_usd if inst.asset_class == "gold" else cm.commission_per_lot_side_usd
    return abs(lots) * rate


def slippage_pips(inst: Instrument, cm: CostModel, news: bool = False, stop: bool = False) -> float:
    s = inst.slippage_pips * cm.slippage_multiplier
    if stop:
        s *= 2  # stop orders fill as market orders in fast markets
    if news:
        s *= cm.news_slippage_multiplier
    return s


def estimate(inst: Instrument, lots: float, spread_price: float, mids: dict[str, float], cm: CostModel, news: bool = False) -> CostEstimate | None:
    pv = pip_value_usd(inst, mids)
    if pv is None:
        return None
    sp_pips = inst.to_pips(spread_price)
    sl = slippage_pips(inst, cm, news)
    return CostEstimate(sp_pips * pv * lots, 2 * commission_per_side(inst, lots, cm), 2 * sl * pv * lots, sp_pips, sl)


def apply_slippage(price: float, pips: float, inst: Instrument, side: str) -> float:
    """Buys fill higher, sells fill lower."""
    d = pips * inst.pip_size
    return price + d if side == "buy" else price - d
