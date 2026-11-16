"""ATLAS AI — MetaTrader 5 bridge (runs on Windows next to a logged-in MT5 terminal).

    pip install MetaTrader5 fastapi uvicorn
    set ATLAS_BRIDGE_TOKEN=<long random string, same value as ATLAS_MT5_BRIDGE_TOKEN on the ATLAS server>
    uvicorn mt5_bridge:app --host 0.0.0.0 --port 8765      # expose ONLY over a VPN / SSH tunnel / firewall allow-list

Credentials: log in to your broker account inside the MT5 terminal (demo account recommended).
This bridge never receives, stores or forwards the MT5 password. Optionally set MT5_PATH to the
terminal64.exe path. Only gold/forex symbols are accepted; every order carries ATLAS's magic number.
"""
from __future__ import annotations

import hmac
import os
import re
from datetime import datetime, timezone

import MetaTrader5 as mt5  # Windows only
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TOKEN = os.environ.get("ATLAS_BRIDGE_TOKEN", "")
ALLOWED = re.compile(r"^(XAUUSD|EURUSD|GBPUSD|USDJPY|GBPJPY|AUDUSD|USDCAD|USDCHF|NZDUSD|EURGBP|EURJPY)[A-Za-z0-9._-]{0,6}$")
TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}

if len(TOKEN) < 24:
    raise SystemExit("set ATLAS_BRIDGE_TOKEN (24+ chars)")
if not mt5.initialize(path=os.environ.get("MT5_PATH") or None):
    raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

app = FastAPI(title="ATLAS MT5 bridge", docs_url=None, openapi_url=None)


def auth(x_bridge_token: str = Header("")):
    if not hmac.compare_digest(x_bridge_token, TOKEN):
        raise HTTPException(401, "unauthorized")


def check(symbol: str) -> str:
    if not ALLOWED.match(symbol):
        raise HTTPException(400, "only gold/forex symbols are allowed")
    if not mt5.symbol_select(symbol, True):
        raise HTTPException(404, f"symbol {symbol} not available at this broker")
    return symbol


def rates_rows(rates):
    return [{k: (float(r[k]) if k != "time" else int(r[k])) for k in ("time", "open", "high", "low", "close", "tick_volume", "spread")} for r in rates]


@app.get("/health", dependencies=[Depends(auth)])
def health():
    return {"terminal": mt5.terminal_info()._asdict()["connected"], "version": mt5.version()}


@app.get("/account", dependencies=[Depends(auth)])
def account():
    a = mt5.account_info()
    if a is None:
        raise HTTPException(503, "terminal not logged in")
    d = a._asdict()
    return {k: d[k] for k in ("login", "trade_mode", "leverage", "balance", "equity", "margin", "margin_free", "currency", "server", "company")}


@app.get("/rates", dependencies=[Depends(auth)])
def rates(symbol: str, timeframe: str, count: int = 500):
    check(symbol)
    r = mt5.copy_rates_from_pos(symbol, TF[timeframe], 0, min(count, 5000))
    return {"rates": rates_rows(r if r is not None else []), "point": mt5.symbol_info(symbol).point}


@app.get("/rates_range", dependencies=[Depends(auth)])
def rates_range(symbol: str, timeframe: str, start: int, end: int):
    check(symbol)
    r = mt5.copy_rates_range(symbol, TF[timeframe], datetime.fromtimestamp(start, timezone.utc), datetime.fromtimestamp(end, timezone.utc))
    return {"rates": rates_rows(r if r is not None else []), "point": mt5.symbol_info(symbol).point}


@app.get("/ticks", dependencies=[Depends(auth)])
def ticks(symbols: str):
    out = []
    for s in symbols.split(",")[:20]:
        check(s)
        t = mt5.symbol_info_tick(s)
        if t:
            out.append({"symbol": s, **{k: getattr(t, k) for k in ("bid", "ask", "last", "time_msc")}})
    return {"ticks": out}


@app.get("/symbol/{symbol}", dependencies=[Depends(auth)])
def symbol_spec(symbol: str):
    check(symbol)
    i = mt5.symbol_info(symbol)._asdict()
    return {k: i[k] for k in ("digits", "point", "trade_contract_size", "volume_min", "volume_step", "volume_max", "spread", "trade_tick_value",
                              "trade_tick_size", "margin_initial", "currency_profit")}


@app.get("/positions", dependencies=[Depends(auth)])
def positions(magic: int):
    ps = mt5.positions_get() or ()
    return {"positions": [p._asdict() for p in ps if p.magic == magic]}


class OrderIn(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    volume: float = Field(gt=0, le=50)
    sl: float = Field(gt=0)
    tp: float = 0
    client_id: str = Field(max_length=31)
    magic: int
    deviation: int = Field(20, ge=0, le=500)


@app.post("/order", dependencies=[Depends(auth)])
def order(o: OrderIn):
    check(o.symbol)
    # duplicate prevention: refuse if a position or recent deal already carries this client id
    if any(p.comment == o.client_id for p in (mt5.positions_get(symbol=o.symbol) or ())):
        raise HTTPException(409, "duplicate client_id")
    tick = mt5.symbol_info_tick(o.symbol)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": o.symbol, "volume": o.volume,
           "type": mt5.ORDER_TYPE_BUY if o.side == "buy" else mt5.ORDER_TYPE_SELL,
           "price": tick.ask if o.side == "buy" else tick.bid, "sl": o.sl, "tp": o.tp, "deviation": o.deviation, "magic": o.magic,
           "comment": o.client_id, "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(req)
    if res is None:
        raise HTTPException(502, f"order_send failed: {mt5.last_error()}")
    d = res._asdict()
    d.pop("request", None)
    pos = next((p for p in (mt5.positions_get(symbol=o.symbol) or ()) if p.comment == o.client_id), None)
    d["position"] = pos.ticket if pos else None
    return d


class ModifyIn(BaseModel):
    ticket: int
    sl: float = Field(gt=0)
    tp: float = 0


@app.post("/modify", dependencies=[Depends(auth)])
def modify(m: ModifyIn):
    p = (mt5.positions_get(ticket=m.ticket) or (None,))[0]
    if p is None:
        raise HTTPException(404, "position not found")
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": m.ticket, "symbol": p.symbol, "sl": m.sl, "tp": m.tp or p.tp})
    return res._asdict() if res else {"retcode": -1}


class CloseIn(BaseModel):
    ticket: int
    volume: float | None = None


@app.post("/close", dependencies=[Depends(auth)])
def close(c: CloseIn):
    p = (mt5.positions_get(ticket=c.ticket) or (None,))[0]
    if p is None:
        raise HTTPException(404, "position not found")
    tick = mt5.symbol_info_tick(p.symbol)
    side_close = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": c.ticket, "symbol": p.symbol, "volume": c.volume or p.volume,
                          "type": side_close, "price": tick.bid if p.type == 0 else tick.ask, "deviation": 50, "magic": p.magic,
                          "comment": "atlas-close", "type_filling": mt5.ORDER_FILLING_IOC})
    d = res._asdict() if res else {"retcode": -1}
    d.pop("request", None)
    d["side"] = "sell" if p.type == 0 else "buy"
    return d


@app.get("/position_history", dependencies=[Depends(auth)])
def position_history(ticket: int):
    deals = mt5.history_deals_get(position=ticket) or ()
    return {"open": bool(mt5.positions_get(ticket=ticket)), "deals": [d._asdict() for d in deals]}


@app.get("/history", dependencies=[Depends(auth)])
def history(since: int, magic: int):
    deals = mt5.history_deals_get(datetime.fromtimestamp(since, timezone.utc), datetime.now(timezone.utc)) or ()
    return {"deals": [d._asdict() for d in deals if d.magic == magic]}
