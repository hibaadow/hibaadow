# ATLAS AI — User Guide (Gold & Forex)

## Roles
viewer: read everything except the audit log and users · trader: analysis/auto-trading toggles, close/flatten
positions, emergency stop, backtests · admin: settings, strategy parameters, trading mode, live arming, release
the emergency stop, users, audit log.

## Pages
- **Dashboard**: balance, equity, daily/weekly/monthly P&L, margin, exposure, a gold analysis card, the forex
  table, active positions, risk gates, net risk by currency, analyst signals, next high-impact events, equity curve,
  pending orders, recent trades and activity.
- **Markets · Gold & Forex**: the two markets ATLAS trades: a GOLD table (XAU/USD) and a FOREX table (10 pairs) with
  bid/ask, spread in pips, 24h change, 1h/4h trend, structure, RSI, ATR, signal, confidence, risk and data status,
  plus the derived currency-strength chart.
- **XAU/USD Workspace**: the dedicated gold terminal. Chart with Asian range, prior-day high/low and position levels;
  session (London/NY overlap); trend, structure, momentum and volatility; USD strength and US10Y yield; USD events;
  the latest gold proposals; and the contract specification.
- **Forex Terminal**: the same terminal for any of the 10 pairs, with base and quote currency strength.
- **AI Analyst**: every proposal (executed or rejected) with direction, entry, stop, target, R:R, lots, costs,
  evidence, events, invalidation, confidence breakdown, risk checks and calibration.
- **Economic Calendar**: this week's events by impact and currency, central-bank events, and the active news-blackout rule.
- **Activity Feed**: a live stream of analysis, proposals, rejections, sizing, fills, stop moves and exits, with explanations.
- **Trade Journal**: closed trades (paper/demo/live tabs, gold/forex filter), searchable, with CSV export and fill-level detail.
- **Performance**: equity curves, drawdown, R distribution, by strategy/instrument/session, costs, calibration. Modes are never mixed.
- **Backtesting**: run, compare, in/out-of-sample and walk-forward.
- **Risk, Brokers & Settings**: limits, per-instrument spread/slippage, news and session filters, automation, instruments,
  costs, trading mode (paper/demo/live), integrations, strategy parameters, users and audit log.

## Typical workflow
1. Start in paper mode. On the public feed, let ATLAS accumulate bars, or connect OANDA practice for instant history.
2. Connect a broker data source and backtest each strategy per instrument. Judge the **out-of-sample** and
   **walk-forward** results.
3. Disable strategies or instruments that don't hold up, then run paper → broker demo for weeks.
4. Consider live only after the checklist in `docs/BROKERS.md`.
