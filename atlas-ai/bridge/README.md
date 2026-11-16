# ATLAS MT5 bridge

MetaTrader 5's Python API only runs on Windows beside a running terminal. Run this bridge on that
machine (a Windows VPS is typical) and point ATLAS at it.

1. Install MetaTrader 5 from your broker, **log in to a demo account**, and enable *Algo Trading*.
2. `pip install MetaTrader5 fastapi uvicorn`
3. `set ATLAS_BRIDGE_TOKEN=<random 32+ chars>` (and optionally `MT5_PATH=C:\...\terminal64.exe`)
4. `uvicorn mt5_bridge:app --host 127.0.0.1 --port 8765`, then expose it to the ATLAS server only through a
   VPN, SSH tunnel or firewall allow-list (never the open internet).
5. On the ATLAS server: `ATLAS_DATA_SOURCE=mt5`, `ATLAS_BROKER=mt5`, `ATLAS_MT5_BRIDGE_URL=http://<host>:8765`,
   `ATLAS_MT5_BRIDGE_TOKEN=<same token>`, `ATLAS_MT5_SYMBOL_SUFFIX` if your broker uses suffixes (e.g. `EURUSD.a`).

The bridge only accepts the 11 gold/forex symbols ATLAS supports, tags every order with ATLAS's magic number
and refuses duplicate client ids. Your MT5 password stays in the terminal.
