"""MetaTrader 5 via MetaApi (metaapi.cloud) — MT5 without Windows.

MetaApi hosts the MT5 terminal in the cloud and exposes it over REST. You add your MT5 (demo) account in
the MetaApi web app (login, password and server are entered THERE, not in ATLAS); ATLAS only needs a
MetaApi API token and the MetaApi account id.

Config: ``ATLAS_METAAPI_TOKEN``, ``ATLAS_METAAPI_ACCOUNT_ID``, optional ``ATLAS_METAAPI_REGION`` (auto-detected),
optional ``ATLAS_MT5_SYMBOL_SUFFIX``.

Endpoints (docs: https://metaapi.cloud/docs/client/):
* provisioning  GET  https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/{id}  → region, state
* client        GET  https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{id}/account-information
                GET  .../positions · .../symbols/{s}/current-price · .../symbols/{s}/specification
                GET  .../history-deals/position/{positionId} · POST .../trade
* market data   GET  https://mt-market-data-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{id}/
                     historical-market-data/symbols/{s}/timeframes/{tf}/candles?startTime=&limit=  (≤1000, loaded backwards)
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from ..config import get_settings
from ..instruments import INSTRUMENTS, get
from ..marketdata.http import ProviderClient, ProviderError
from ..marketdata.types import TF_MS, Candle, Quote
from .base import AccountInfo, BrokerError, BrokerFill, BrokerTrade

PROVISIONING = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
DONE = ("TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE_PARTIAL")


def _iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def short_client_id(client_id: str) -> str:
    """Deterministic id within MetaApi's 26-char clientId+comment limit (same input → same id → duplicates detectable)."""
    return "AT" + hashlib.sha1(client_id.encode()).hexdigest()[:18]


class MetaApiClient:
    name = "metaapi"

    def __init__(self):
        s = get_settings()
        if not s.metaapi_configured:
            raise BrokerError("MetaApi is not configured: set ATLAS_METAAPI_TOKEN and ATLAS_METAAPI_ACCOUNT_ID")
        self.account_id = s.metaapi_account_id
        self.suffix = s.mt5_symbol_suffix
        self.magic = s.mt5_magic
        self.region = s.metaapi_region
        self.environment = "demo"
        self._headers = {"auth-token": s.metaapi_token.get_secret_value()}
        self.prov = ProviderClient("metaapi_provisioning", PROVISIONING, rate_per_sec=1, burst=2, max_retries=1, headers=self._headers)
        self.client: ProviderClient | None = None
        self.mdata: ProviderClient | None = None
        self._specs: dict[str, dict] = {}
        self.state: str | None = None

    # ------------------------------------------------------------------ plumbing
    async def _ensure(self) -> None:
        if self.client is not None:
            return
        try:
            acc = await self.prov.get(f"/users/current/accounts/{self.account_id}")
        except ProviderError as e:
            raise BrokerError(f"MetaApi account lookup failed: {e}") from e
        self.state = acc.get("state")
        if self.state != "DEPLOYED":
            raise BrokerError(f"MetaApi account is {self.state or 'unknown'} — deploy it in the MetaApi web app")
        self.region = self.region or acc.get("region") or "new-york"
        acct = f"/users/current/accounts/{self.account_id}"
        self.client = ProviderClient("metaapi", f"https://mt-client-api-v1.{self.region}.agiliumtrade.ai{acct}",
                                     rate_per_sec=10, burst=20, max_retries=2, headers=self._headers, timeout=60)
        self.mdata = ProviderClient("metaapi_market_data", f"https://mt-market-data-client-api-v1.{self.region}.agiliumtrade.ai{acct}",
                                    rate_per_sec=5, burst=10, max_retries=1, headers=self._headers, timeout=120)

    def sym(self, symbol: str) -> str:
        return get(symbol).symbol + self.suffix

    def unsym(self, broker_symbol: str) -> str | None:
        s = broker_symbol[: len(broker_symbol) - len(self.suffix)] if self.suffix and broker_symbol.endswith(self.suffix) else broker_symbol
        return s if s in INSTRUMENTS else None

    async def spec(self, symbol: str) -> dict:
        if symbol not in self._specs:
            await self._ensure()
            self._specs[symbol] = await self.client.get(f"/symbols/{self.sym(symbol)}/specification")
        return self._specs[symbol]

    async def _point(self, symbol: str) -> float:
        try:
            return float((await self.spec(symbol)).get("tickSize") or 0) or 10 ** -get(symbol).digits
        except ProviderError:
            return 10 ** -get(symbol).digits

    # ------------------------------------------------------------------ market data
    async def _candles(self, symbol: str, tf: str, limit: int, start_time: str | None = None) -> list[Candle]:
        await self._ensure()
        rows = await self.mdata.get(f"/historical-market-data/symbols/{self.sym(symbol)}/timeframes/{tf}/candles",
                                    limit=min(limit, 1000), startTime=start_time)
        pt = await self._point(symbol)
        out = []
        for r in rows if isinstance(rows, list) else []:
            try:
                out.append(Candle(_iso_ms(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                                  float(r.get("tickVolume", 0)), 0.0, float(r.get("spread", 0)) * pt))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(out, key=lambda c: c.open_time)

    async def candles(self, symbol: str, tf: str, count: int = 500) -> list[Candle]:
        now = int(time.time() * 1000)
        return [c for c in await self._candles(symbol, tf, count + 1) if c.open_time + TF_MS[tf] <= now][-count:]  # drop forming bar

    async def history(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> list[Candle]:
        out: dict[int, Candle] = {}
        cursor = end_ms
        for _ in range(200):
            batch = await self._candles(symbol, tf, 1000, datetime.fromtimestamp(cursor / 1000, timezone.utc).isoformat().replace("+00:00", "Z"))
            batch = [c for c in batch if c.open_time < cursor]
            if not batch:
                break
            for c in batch:
                if c.open_time >= start_ms:
                    out[c.open_time] = c
            if batch[0].open_time <= start_ms:
                break
            cursor = batch[0].open_time
        return [out[k] for k in sorted(out)]

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        await self._ensure()
        out = {}
        for s in symbols:
            try:
                p = await self.client.get(f"/symbols/{self.sym(s)}/current-price", keepSubscription="true")
                bid, ask = float(p["bid"]), float(p["ask"])
                if bid > 0 and ask >= bid:
                    q = Quote(s, "metaapi", bid, ask, (bid + ask) / 2)
                    q.ts = min(time.time(), _iso_ms(p["time"]) / 1000)
                    out[s] = q
            except (ProviderError, KeyError, TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------ account & execution
    async def account(self) -> AccountInfo:
        await self._ensure()
        a = await self.client.get("/account-information")
        self.environment = "live" if a.get("type") == "ACCOUNT_TRADE_MODE_REAL" else "demo"
        return AccountInfo("metaapi", self.environment, a.get("currency", "USD"), float(a["balance"]), float(a["equity"]), float(a["margin"]),
                           float(a["freeMargin"]), float(a.get("leverage") or 0) or None,
                           {"server": a.get("server"), "broker": a.get("broker"), "platform": a.get("platform"), "trade_allowed": a.get("tradeAllowed")})

    async def _positions(self) -> list[dict]:
        await self._ensure()
        rows = await self.client.get("/positions")
        return rows if isinstance(rows, list) else []

    async def open_trades(self) -> list[BrokerTrade]:
        out = []
        for p in await self._positions():
            sym = self.unsym(p.get("symbol", ""))
            if not sym or p.get("magic") != self.magic:
                continue
            out.append(BrokerTrade(str(p["id"]), sym, "buy" if p["type"] == "POSITION_TYPE_BUY" else "sell", float(p["volume"]), float(p["openPrice"]),
                                   float(p["stopLoss"]) if p.get("stopLoss") else None, float(p["takeProfit"]) if p.get("takeProfit") else None,
                                   float(p.get("unrealizedProfit", p.get("profit", 0))), p.get("clientId"), p.get("time")))
        return out

    async def _trade(self, body: dict) -> dict:
        await self._ensure()
        try:
            r = await self.client.post("/trade", body)
        except ProviderError as e:
            raise BrokerError(f"MetaApi trade request failed: {e}") from e
        if r.get("stringCode") not in DONE:
            raise BrokerError(f"MT5 rejected {body.get('actionType')}: {r.get('stringCode')} ({r.get('numericCode')}) {r.get('message', '')}")
        return r

    async def market_order(self, symbol, side, lots, stop_loss, take_profit, client_id, max_slippage_price=None,
                           max_slippage_pips=None) -> BrokerFill:
        inst = get(symbol)
        cid = short_client_id(client_id)
        if any(p.get("clientId") == cid for p in await self._positions()):
            raise BrokerError(f"duplicate order {client_id} prevented (already open at broker)")
        body = {"actionType": "ORDER_TYPE_BUY" if side == "buy" else "ORDER_TYPE_SELL", "symbol": self.sym(symbol), "volume": round(lots, 2),
                "stopLoss": round(stop_loss, inst.digits), "clientId": cid, "magic": self.magic}
        if take_profit:
            body["takeProfit"] = round(take_profit, inst.digits)
        if max_slippage_pips is not None:
            body["slippage"] = max(0, int(round(max_slippage_pips * inst.pip_size / await self._point(symbol))))  # in points
        r = await self._trade(body)
        pos = next((p for p in await self._positions() if p.get("clientId") == cid), None)
        if pos is None:
            raise BrokerError(f"order {r.get('orderId')} accepted but no open position found — check the MT5 account")
        return BrokerFill(str(pos["id"]), str(r.get("orderId", "")), symbol, side, float(pos["volume"]), float(pos["openPrice"]),
                          abs(float(pos.get("commission", 0))), 0.0, 0.0, r)

    async def modify_stop(self, broker_id, symbol, stop_loss, take_profit=None) -> None:
        inst = get(symbol)
        body = {"actionType": "POSITION_MODIFY", "positionId": str(broker_id), "stopLoss": round(stop_loss, inst.digits)}
        if take_profit:
            body["takeProfit"] = round(take_profit, inst.digits)
        await self._trade(body)

    async def _deals(self, broker_id: str) -> list[dict]:
        await self._ensure()
        rows = await self.client.get(f"/history-deals/position/{broker_id}")
        return rows if isinstance(rows, list) else []

    async def close_trade(self, broker_id, symbol, lots=None) -> BrokerFill:
        before = {d.get("id") for d in await self._deals(broker_id)}
        body = {"actionType": "POSITION_CLOSE_ID", "positionId": str(broker_id)} if lots is None else \
               {"actionType": "POSITION_PARTIAL", "positionId": str(broker_id), "volume": round(lots, 2)}
        r = await self._trade(body)
        new = [d for d in await self._deals(broker_id) if d.get("id") not in before and d.get("entryType") in ("DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY")]
        vol = sum(float(d.get("volume", 0)) for d in new)
        px = sum(float(d.get("price", 0)) * float(d.get("volume", 0)) for d in new) / vol if vol else 0.0
        side = "sell" if any(d.get("type") == "DEAL_TYPE_SELL" for d in new) else "buy"
        return BrokerFill(str(broker_id), str(r.get("orderId", "")), symbol, side, round(vol or (lots or 0.0), 2), get(symbol).round_price(px),
                          abs(sum(float(d.get("commission", 0)) for d in new)), -sum(float(d.get("swap", 0)) for d in new),
                          sum(float(d.get("profit", 0)) for d in new), r)

    async def trade_details(self, broker_id: str) -> dict:
        if any(str(p.get("id")) == str(broker_id) for p in await self._positions()):
            return {"state": "OPEN"}
        deals = await self._deals(broker_id)
        exits = [d for d in deals if d.get("entryType") in ("DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY")]
        if not exits:
            return {"state": "OPEN"}
        vol = sum(float(d.get("volume", 0)) for d in exits)
        return {"state": "CLOSED", "close_price": sum(float(d["price"]) * float(d["volume"]) for d in exits) / vol if vol else None,
                "realized_pnl": sum(float(d.get("profit", 0)) for d in exits), "financing": sum(float(d.get("swap", 0)) for d in deals),
                "commission": abs(sum(float(d.get("commission", 0)) for d in deals))}

    def health(self) -> dict:
        out = {"metaapi_provisioning": self.prov.health()}
        if self.client is not None:
            out["metaapi"] = self.client.health()
        if self.mdata is not None:
            out["metaapi_market_data"] = self.mdata.health()
        return out

    async def close(self) -> None:
        for c in (self.prov, self.client, self.mdata):
            if c is not None:
                await c.close()
