"""Common broker / data-source interfaces."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..marketdata.types import Candle, Quote


class BrokerError(Exception):
    pass


@dataclass
class AccountInfo:
    broker: str
    environment: str  # demo | live
    currency: str
    balance: float
    equity: float
    margin_used: float
    margin_free: float
    leverage: float | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class BrokerTrade:
    broker_id: str
    symbol: str
    side: str  # buy | sell
    lots: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    unrealized_pnl: float
    client_id: str | None = None
    open_time: str | None = None


@dataclass
class BrokerFill:
    broker_id: str  # trade/position id
    order_id: str
    symbol: str
    side: str
    lots: float
    price: float
    commission: float = 0.0
    financing: float = 0.0
    realized_pnl: float = 0.0
    raw: dict = field(default_factory=dict)


class DataSource(Protocol):
    name: str

    async def candles(self, symbol: str, tf: str, count: int) -> list[Candle]: ...

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    def health(self) -> dict: ...

    async def close(self) -> None: ...


class Broker(Protocol):
    name: str
    environment: str

    async def account(self) -> AccountInfo: ...

    async def open_trades(self) -> list[BrokerTrade]: ...

    async def market_order(self, symbol: str, side: str, lots: float, stop_loss: float, take_profit: float | None,
                           client_id: str, max_slippage_price: float | None = None) -> BrokerFill: ...

    async def modify_stop(self, broker_id: str, symbol: str, stop_loss: float, take_profit: float | None = None) -> None: ...

    async def close_trade(self, broker_id: str, symbol: str, lots: float | None = None) -> BrokerFill: ...

    async def close(self) -> None: ...
