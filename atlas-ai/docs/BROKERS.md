# Broker & data setup

ATLAS separates **where data comes from** (`ATLAS_DATA_SOURCE`) from **where orders go** (`ATLAS_BROKER`).
Credentials are read from the environment only (or stay inside the MT5 terminal). They are never stored in the
database, returned by the API, logged, or sent to any AI model.

## 1. No credentials (default)
`ATLAS_DATA_SOURCE=public`, `ATLAS_BROKER=none` → paper trading on live Swissquote quotes. Bars are built from sampled
quotes and accumulate while ATLAS runs.

## 2. OANDA v20 (recommended first broker — free practice account)
1. Open a practice (demo) account at OANDA and generate a personal access token (*Manage API Access*).
2. Find your v20 account id (format `101-001-1234567-001`).
3. In `.env`:
   ```
   ATLAS_DATA_SOURCE=oanda
   ATLAS_BROKER=oanda
   ATLAS_OANDA_ENVIRONMENT=practice
   ATLAS_OANDA_TOKEN=<token>
   ATLAS_OANDA_ACCOUNT_ID=<account id>
   ```
4. Restart. Settings → Integrations should show *OANDA* and *OANDA account* as OK, and the account as **DEMO**.
5. Settings → Trading mode → **Broker demo**. Turn on *Auto trading* when you are ready.

Endpoints used: `GET /v3/instruments/{i}/candles?price=BA`, `GET /v3/accounts/{id}/pricing`, `GET /v3/accounts/{id}/summary`,
`GET /openTrades`, `POST /orders` (MARKET, FOK, `stopLossOnFill`, `takeProfitOnFill`, `priceBound`, `clientExtensions`),
`PUT /trades/{id}/orders`, `PUT /trades/{id}/close`, `GET /trades/{id}`. Symbols map to `XAU_USD`, `EUR_USD`, …

Live: set `ATLAS_OANDA_ENVIRONMENT=live`, `ATLAS_LIVE_TRADING_ALLOWED=true`, use a live token/account, then arm live in Settings.

## 3. MetaTrader 5 (priority broker integration)
The MetaTrader5 Python API only runs on Windows next to a running terminal, so ATLAS uses a small bridge:
1. On a Windows PC or VPS: install your broker's MT5, **log in to a demo account**, and enable *Algo Trading*.
2. Copy `bridge/mt5_bridge.py` there, then run `pip install MetaTrader5 fastapi uvicorn`.
3. Set `ATLAS_BRIDGE_TOKEN` (32+ random chars) and run `uvicorn mt5_bridge:app --host 127.0.0.1 --port 8765`. Expose it to
   the ATLAS server only over a VPN, SSH tunnel or firewall allow-list.
4. On the ATLAS server:
   ```
   ATLAS_DATA_SOURCE=mt5
   ATLAS_BROKER=mt5
   ATLAS_MT5_BRIDGE_URL=http://<bridge-host>:8765
   ATLAS_MT5_BRIDGE_TOKEN=<same token>
   ATLAS_MT5_SYMBOL_SUFFIX=<e.g. .a, if your broker uses suffixes>
   ```
5. The account type (demo/live) is read from the terminal. ATLAS refuses to trade if it doesn't match the selected mode.

The bridge accepts only the 11 gold/forex symbols, tags every order with ATLAS's magic number, refuses duplicate
client ids, and attaches SL/TP to every order. **Check your broker's contract specs** (`GET /symbol/{s}` on the
bridge): gold contract sizes, digits and minimum lots differ between brokers.

## 4. Mixed setups
You can use OANDA for data and MT5 for execution (or the reverse). The public quote feed always runs as an
independent price reference when a broker supplies the data.

## Safety checklist before going live
- Run demo for weeks and compare demo results with paper and backtests.
- Verify contract size, pip value and minimum lot for XAU/USD at your broker.
- Keep `ATLAS_LIVE_TRADING_ALLOWED=false` until you have completed the above.
- Start live with the minimum risk per trade (e.g. 0.25 %).
