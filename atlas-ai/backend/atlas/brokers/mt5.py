"""MetaTrader 5 adapter.

The official ``MetaTrader5`` Python package only runs on Windows next to a running MT5 terminal.
ATLAS therefore talks to MT5 through a small authenticated HTTP bridge (``bridge/mt5_bridge.py``)
that you run on the Windows machine/VPS hosting the terminal. The MT5 login, password and server
are entered in the terminal (or the bridge's own environment) — never in ATLAS.

Config: ``ATLAS_MT5_BRIDGE_URL``, ``ATLAS_MT5_BRIDGE_TOKEN``, optional ``ATLAS_MT5_SYMBOL_SUFFIX``.
"""
from __future__ import annotations

from ..config import get_settings
from ..instruments import INSTRUMENTS, get
from ..marketdata.http import ProviderClient, ProviderError
from ..marketdata.types import Candle, Quote
from .base import AccountInfo, BrokerError, BrokerFill, BrokerTrade

TF = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4"}


class MT5Client:
    name = "mt5"

    def __init__(self):
        s = get_settings()
        if not s.mt5_configured:
            raise BrokerError("MT5 is not configured: set ATLAS_MT5_BRIDGE_URL and ATLAS_MT5_BRIDGE_TOKEN")
        token = s.mt5_bridge_token.get_secret_value() if s.mt5_bridge_token else ""
        self.http = ProviderClient("mt5_bridge", s.mt5_bridge_url, rate_per_sec=20, burst=30, max_retries=1, headers={"X-Bridge-Token": token})
        self.suffix = s.mt5_symbol_suffix
        self.magic = s.mt5_magic
        self.environment = "demo"  # updated from the terminal's account trade_mode on first account() call

    def sym(self, symbol: str) -> str:
        return get(symbol).symbol + self.suffix

    def unsym(self, broker_symbol: str) -> str | None:
        s = broker_symbol[: len(broker_symbol) - len(self.suffix)] if self.suffix and broker_symbol.endswith(self.suffix) else broker_symbol
        return s if s in INSTRUMENTS else None

    async def candles(self, symbol: str, tf: str, count: int = 500) -> list[Candle]:
        d = await self.http.get("/rates", symbol=self.sym(symbol), timeframe=TF[tf], count=count + 1)
        pt = d.get("point", get(symbol).pip_size / 10)
        rows = d.get("rates", [])[:-1]  # last row is the forming bar
        return [Candle(int(r["time"]) * 1000, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                       float(r.get("tick_volume", 0)), 0.0, float(r.get("spread", 0)) * pt) for r in rows]

    async def history(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> list[Candle]:
        d = await self.http.get("/rates_range", symbol=self.sym(symbol), timeframe=TF[tf], start=start_ms // 1000, end=end_ms // 1000)
        pt = d.get("point", get(symbol).pip_size / 10)
        return [Candle(int(r["time"]) * 1000, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                       float(r.get("tick_volume", 0)), 0.0, float(r.get("spread", 0)) * pt) for r in d.get("rates", [])]

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        d = await self.http.get("/ticks", symbols=",".join(self.sym(s) for s in symbols))
        out = {}
        for row in d.get("ticks", []):
            sym = self.unsym(row.get("symbol", ""))
            try:
                if sym and float(row["bid"]) > 0:
                    q = Quote(sym, "mt5", float(row["bid"]), float(row["ask"]), float(row.get("last") or 0) or (float(row["bid"]) + float(row["ask"])) / 2)
                    q.ts = float(row["time_msc"]) / 1000 if row.get("time_msc") else q.ts
                    out[sym] = q
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def account(self) -> AccountInfo:
        a = await self.http.get("/account")
        self.environment = "demo" if a.get("trade_mode") == 0 else "live"  # ACCOUNT_TRADE_MODE_DEMO == 0
        return AccountInfo("mt5", self.environment, a.get("currency", "USD"), float(a["balance"]), float(a["equity"]), float(a["margin"]),
                           float(a["margin_free"]), float(a.get("leverage") or 0) or None, {"server": a.get("server"), "company": a.get("company")})

    async def open_trades(self) -> list[BrokerTrade]:
        d = await self.http.get("/positions", magic=self.magic)
        out = []
        for p in d.get("positions", []):
            sym = self.unsym(p.get("symbol", ""))
            if not sym:
                continue
            out.append(BrokerTrade(str(p["ticket"]), sym, "buy" if p["type"] == 0 else "sell", float(p["volume"]), float(p["price_open"]),
                                   float(p["sl"]) or None, float(p["tp"]) or None, float(p.get("profit", 0)), p.get("comment"), str(p.get("time"))))
        return out

    async def market_order(self, symbol, side, lots, stop_loss, take_profit, client_id, max_slippage_price=None) -> BrokerFill:
        inst = get(symbol)
        deviation = int(round(abs(max_slippage_price) / (inst.pip_size / 10))) if max_slippage_price else 20
        try:
            d = await self.http.post("/order", {"symbol": self.sym(symbol), "side": side, "volume": lots, "sl": stop_loss, "tp": take_profit or 0,
                                                "client_id": client_id[:31], "magic": self.magic, "deviation": deviation})
        except ProviderError as e:
            raise BrokerError(f"MT5 order failed: {e}") from e
        if d.get("retcode") not in (10009, 10008):  # TRADE_RETCODE_DONE / PLACED
            raise BrokerError(f"MT5 order rejected: retcode {d.get('retcode')} {d.get('comment', '')}")
        return BrokerFill(str(d.get("position") or d.get("order")), str(d.get("order")), symbol, side, float(d.get("volume", lots)), float(d["price"]),
                          float(d.get("commission", 0)), 0.0, 0.0, d)

    async def modify_stop(self, broker_id, symbol, stop_loss, take_profit=None) -> None:
        d = await self.http.post("/modify", {"ticket": int(broker_id), "sl": stop_loss, "tp": take_profit or 0})
        if d.get("retcode") != 10009:
            raise BrokerError(f"MT5 modify rejected: retcode {d.get('retcode')}")

    async def close_trade(self, broker_id, symbol, lots=None) -> BrokerFill:
        d = await self.http.post("/close", {"ticket": int(broker_id), "volume": lots})
        if d.get("retcode") != 10009:
            raise BrokerError(f"MT5 close rejected: retcode {d.get('retcode')} {d.get('comment', '')}")
        return BrokerFill(broker_id, str(d.get("order")), symbol, d.get("side", ""), float(d.get("volume", lots or 0)), float(d["price"]),
                          float(d.get("commission", 0)), float(d.get("swap", 0)), float(d.get("profit", 0)), d)

    async def trade_details(self, broker_id: str) -> dict:
        d = await self.http.get("/position_history", ticket=int(broker_id))
        deals = d.get("deals", [])
        open_now = d.get("open", False)
        exits = [x for x in deals if x.get("entry") in (1, 3)]  # DEAL_ENTRY_OUT / OUT_BY
        if open_now or not exits:
            return {"state": "OPEN"}
        vol = sum(float(x["volume"]) for x in exits)
        px = sum(float(x["price"]) * float(x["volume"]) for x in exits) / vol if vol else None
        return {"state": "CLOSED", "close_price": px, "realized_pnl": sum(float(x.get("profit", 0)) for x in exits),
                "financing": sum(float(x.get("swap", 0)) for x in deals), "commission": sum(float(x.get("commission", 0)) for x in deals)}

    def health(self) -> dict:
        return {"mt5_bridge": self.http.health()}

    async def close(self) -> None:
        await self.http.close()
