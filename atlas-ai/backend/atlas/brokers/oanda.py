"""OANDA v20 REST adapter (market data + execution). Practice (demo) environment by default.

Credentials: ``ATLAS_OANDA_TOKEN`` and ``ATLAS_OANDA_ACCOUNT_ID`` from the environment only.
Docs: https://developer.oanda.com/rest-live-v20/introduction/
"""
from __future__ import annotations

from datetime import datetime

from ..config import get_settings
from ..instruments import INSTRUMENTS, get
from ..marketdata.http import ProviderClient, ProviderError
from ..marketdata.types import Candle, Quote
from .base import AccountInfo, BrokerError, BrokerFill, BrokerTrade

GRAN = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4"}
HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}


def _ts(s: str) -> int:
    # "2026-11-16T19:00:00.000000000Z" → ms
    base = s.split(".")[0].rstrip("Z")
    return int(datetime.fromisoformat(base + "+00:00").timestamp() * 1000)


def parse_candles(payload: dict) -> list[Candle]:
    out = []
    for c in payload.get("candles", []):
        if not c.get("complete", False):
            continue  # never use the forming bar
        try:
            mid = c.get("mid") or {}
            bid, ask = c.get("bid"), c.get("ask")
            if bid and ask:
                spread = (float(ask["c"]) - float(bid["c"]) + float(ask["o"]) - float(bid["o"])) / 2
                o = (float(bid["o"]) + float(ask["o"])) / 2
                h = (float(bid["h"]) + float(ask["h"])) / 2
                l = (float(bid["l"]) + float(ask["l"])) / 2
                cl = (float(bid["c"]) + float(ask["c"])) / 2
            else:
                spread, o, h, l, cl = 0.0, float(mid["o"]), float(mid["h"]), float(mid["l"]), float(mid["c"])
            out.append(Candle(_ts(c["time"]), o, h, l, cl, float(c.get("volume", 0)), 0.0, max(spread, 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


class OandaClient:
    name = "oanda"

    def __init__(self, environment: str | None = None):
        s = get_settings()
        if not s.oanda_configured:
            raise BrokerError("OANDA is not configured: set ATLAS_OANDA_TOKEN and ATLAS_OANDA_ACCOUNT_ID")
        self.environment = "demo" if (environment or s.oanda_environment) == "practice" else "live"
        if self.environment == "live" and not s.live_trading_allowed:
            raise BrokerError("OANDA live environment requested but ATLAS_LIVE_TRADING_ALLOWED is false")
        self.account_id = s.oanda_account_id
        self.http = ProviderClient("oanda", HOSTS[environment or s.oanda_environment], rate_per_sec=20, burst=30, max_retries=2,
                                   headers={"Authorization": f"Bearer {s.oanda_token.get_secret_value()}",
                                            "Accept-Datetime-Format": "RFC3339", "Content-Type": "application/json"})

    # ---------------- data
    async def candles(self, symbol: str, tf: str, count: int = 500) -> list[Candle]:
        d = await self.http.get(f"/v3/instruments/{get(symbol).oanda}/candles", granularity=GRAN[tf], count=min(count, 5000), price="BA")
        return parse_candles(d)

    async def history(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> list[Candle]:
        out: list[Candle] = []
        cursor = start_ms
        while cursor < end_ms:
            frm = datetime.utcfromtimestamp(cursor / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
            d = await self.http.get(f"/v3/instruments/{get(symbol).oanda}/candles", granularity=GRAN[tf], price="BA", count=5000, **{"from": frm})
            batch = [c for c in parse_candles(d) if c.open_time < end_ms]
            if not batch or batch[-1].open_time <= cursor:
                break
            out.extend(batch)
            cursor = batch[-1].open_time + 1
        return out

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        names = ",".join(get(s).oanda for s in symbols)
        d = await self.http.get(f"/v3/accounts/{self.account_id}/pricing", instruments=names)
        rev = {get(s).oanda: s for s in symbols}
        out = {}
        for p in d.get("prices", []):
            try:
                sym = rev[p["instrument"]]
                bid, ask = float(p["bids"][0]["price"]), float(p["asks"][0]["price"])
                q = Quote(sym, "oanda", bid, ask, (bid + ask) / 2)
                q.ts = _ts(p["time"]) / 1000
                if p.get("tradeable", True):
                    out[sym] = q
            except (KeyError, IndexError, ValueError):
                continue
        return out

    # ---------------- account / execution
    async def account(self) -> AccountInfo:
        a = (await self.http.get(f"/v3/accounts/{self.account_id}/summary"))["account"]
        lev = 1 / float(a["marginRate"]) if float(a.get("marginRate") or 0) > 0 else None
        return AccountInfo("oanda", self.environment, a["currency"], float(a["balance"]), float(a["NAV"]), float(a["marginUsed"]),
                           float(a["marginAvailable"]), lev, {"openTradeCount": a.get("openTradeCount")})

    async def open_trades(self) -> list[BrokerTrade]:
        d = await self.http.get(f"/v3/accounts/{self.account_id}/openTrades")
        out = []
        for t in d.get("trades", []):
            sym = t["instrument"].replace("_", "")
            if sym not in INSTRUMENTS:
                continue
            units = float(t["currentUnits"])
            out.append(BrokerTrade(t["id"], sym, "buy" if units > 0 else "sell", abs(units) / INSTRUMENTS[sym].contract_size, float(t["price"]),
                                   float(t["stopLossOrder"]["price"]) if t.get("stopLossOrder") else None,
                                   float(t["takeProfitOrder"]["price"]) if t.get("takeProfitOrder") else None,
                                   float(t.get("unrealizedPL", 0)), (t.get("clientExtensions") or {}).get("id"), t.get("openTime")))
        return out

    async def market_order(self, symbol, side, lots, stop_loss, take_profit, client_id, max_slippage_price=None,
                           max_slippage_pips=None) -> BrokerFill:
        inst = get(symbol)
        units = round(lots * inst.contract_size) * (1 if side == "buy" else -1)
        order = {"type": "MARKET", "instrument": inst.oanda, "units": str(units), "timeInForce": "FOK", "positionFill": "DEFAULT",
                 "stopLossOnFill": {"price": f"{stop_loss:.{inst.digits}f}", "timeInForce": "GTC"},
                 "clientExtensions": {"id": client_id[:120], "tag": "atlas-ai"},
                 "tradeClientExtensions": {"id": client_id[:120], "tag": "atlas-ai"}}
        if take_profit:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.{inst.digits}f}", "timeInForce": "GTC"}
        if max_slippage_price is not None:
            order["priceBound"] = f"{max_slippage_price:.{inst.digits}f}"
        try:
            d = await self.http.post(f"/v3/accounts/{self.account_id}/orders", {"order": order})
        except ProviderError as e:
            raise BrokerError(f"OANDA order rejected: {e}") from e
        fill = d.get("orderFillTransaction")
        if not fill:
            reason = (d.get("orderCancelTransaction") or d.get("orderRejectTransaction") or {}).get("reason", "unknown")
            raise BrokerError(f"OANDA order not filled: {reason}")
        trade_id = (fill.get("tradeOpened") or {}).get("tradeID") or ""
        return BrokerFill(trade_id, fill["id"], symbol, side, abs(float(fill["units"])) / inst.contract_size, float(fill["price"]),
                          -float(fill.get("commission", 0)), float(fill.get("financing", 0)), float(fill.get("pl", 0)), fill)

    async def modify_stop(self, broker_id, symbol, stop_loss, take_profit=None) -> None:
        inst = get(symbol)
        body = {"stopLoss": {"price": f"{stop_loss:.{inst.digits}f}", "timeInForce": "GTC"}}
        if take_profit:
            body["takeProfit"] = {"price": f"{take_profit:.{inst.digits}f}", "timeInForce": "GTC"}
        await self.http.put(f"/v3/accounts/{self.account_id}/trades/{broker_id}/orders", body)

    async def close_trade(self, broker_id, symbol, lots=None) -> BrokerFill:
        inst = get(symbol)
        units = "ALL" if lots is None else str(round(lots * inst.contract_size))
        d = await self.http.put(f"/v3/accounts/{self.account_id}/trades/{broker_id}/close", {"units": units})
        f = d.get("orderFillTransaction")
        if not f:
            raise BrokerError(f"OANDA close failed: {(d.get('orderCancelTransaction') or {}).get('reason', 'unknown')}")
        return BrokerFill(broker_id, f["id"], symbol, "sell" if float(f["units"]) < 0 else "buy", abs(float(f["units"])) / inst.contract_size,
                          float(f["price"]), -float(f.get("commission", 0)), float(f.get("financing", 0)), float(f.get("pl", 0)), f)

    async def trade_details(self, broker_id: str) -> dict:
        """State of a trade: OPEN or CLOSED (with average close price and realised P&L in account currency)."""
        t = (await self.http.get(f"/v3/accounts/{self.account_id}/trades/{broker_id}"))["trade"]
        return {"state": t["state"], "close_price": float(t["averageClosePrice"]) if t.get("averageClosePrice") else None,
                "realized_pnl": float(t.get("realizedPL", 0)), "financing": float(t.get("financing", 0)),
                "units": abs(float(t.get("initialUnits", 0))), "close_time": t.get("closeTime")}

    def health(self) -> dict:
        return {"oanda": self.http.health()}

    async def close(self) -> None:
        await self.http.close()
