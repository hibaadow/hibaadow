"""Transaction cost model shared by risk sizing, paper execution and backtesting."""
from __future__ import annotations

from dataclasses import dataclass

from ..trading_config import FeeModel


@dataclass
class CostEstimate:
    fee_bps: float
    slippage_bps: float
    spread_bps: float

    @property
    def total_bps(self) -> float:
        return self.fee_bps + self.slippage_bps


def slippage_bps(fees: FeeModel, notional: float, minute_quote_volume: float | None, spread_bps: float) -> float:
    """Base slippage + half the spread + market impact proportional to participation.

    impact = impact_coefficient bps for every 1% of the average 1-minute quote
    volume consumed. If volume is unknown we assume a thin market (conservative).
    """
    if minute_quote_volume and minute_quote_volume > 0:
        participation_pct = notional / minute_quote_volume * 100
    else:
        participation_pct = 50.0
    return fees.base_slippage_bps + max(spread_bps, 0) / 2 + fees.impact_coefficient * participation_pct


def estimate(fees: FeeModel, notional: float, minute_quote_volume: float | None, spread_bps: float, taker: bool = True) -> CostEstimate:
    return CostEstimate(fees.taker_fee_bps if taker else fees.maker_fee_bps,
                        slippage_bps(fees, notional, minute_quote_volume, spread_bps), spread_bps)


def fee(fees: FeeModel, notional: float, taker: bool = True) -> float:
    return abs(notional) * (fees.taker_fee_bps if taker else fees.maker_fee_bps) / 1e4


def apply_slippage(price: float, bps: float, side: str) -> float:
    """Buys fill higher, sells fill lower."""
    return price * (1 + bps / 1e4) if side == "buy" else price * (1 - bps / 1e4)
