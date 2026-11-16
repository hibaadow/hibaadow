export type Check = { name: string; passed: boolean; detail: string };

export type Overview = {
  mode: string; starting_capital: number; equity: number; cash: number; available_capital: number; positions_value: number;
  unrealized_pnl: number; realized_pnl: number; open_positions: number; max_drawdown_pct: number; day_pnl: number; day_pnl_pct: number;
  week_pnl: number; week_pnl_pct: number; month_pnl: number; month_pnl_pct: number; total_trades: number; wins: number; losses: number;
  win_rate: number | null; profit_factor: number | null; profit_factor_note?: string; avg_win: number | null; avg_loss: number | null;
  net_pnl: number; expectancy: number | null; expectancy_r?: number | null; fees_paid: number; slippage_cost: number;
  gates: Check[]; trading_allowed: boolean; halt: string | null; results_label: string;
  agent: { alive: boolean; ts?: number; cycle?: number; last_scan?: number | null; last_error?: string | null; feeds?: Record<string, { status: string }> };
  config: { mode: string; kill_switch: boolean; trading_enabled: boolean; scanning: boolean; auto_paper: boolean; risk_per_trade_pct: number };
};

export type ScannerRow = {
  symbol: string; base: string; price: number | null; change_24h_pct: number | null; volume_24h_usd: number | null; market_cap: number | null;
  liquidity_usd: number | null; spread_bps: number | null; data_ok: boolean; data_issues: string[]; rsi: number | null; trend: string;
  volatility_pct: number | null; signal: string; confidence: number; strategy: string | null; risk_rating: string; updated: number;
};

export type Position = {
  id: number; mode: string; symbol: string; strategy: string; side: string; status: string; opened_at: string | null; closed_at: string | null;
  created_at: string; qty: number; initial_qty: number; entry_price: number; exit_price: number | null; stop_price: number; initial_stop: number;
  tp1: number; tp2: number | null; tp1_hit: boolean; risk_amount: number; fees: number; slippage: number; gross_pnl: number; net_pnl: number;
  r_multiple: number | null; rr: number | null; position_value: number; last_price: number | null; unrealized_pnl: number; entry_reason: string;
  exit_reason: string | null; duration_s: number | null; decision_id: number | null; stop_history: { ts: string; stop: number; reason: string }[];
};

export type Order = {
  id: number; client_order_id: string; mode: string; position_id: number | null; symbol: string; side: string; type: string; purpose: string;
  qty: number; filled_qty: number; limit_price: number | null; stop_price: number | null; avg_fill_price: number | null; status: string;
  fees: number; reason: string | null; venue: string; created_at: string;
};

export type Activity = { id: number; ts: string; kind: string; symbol: string | null; message: string; explanation: string | null; data: Record<string, unknown> };

export type Decision = {
  id: number; ts: string; symbol: string; strategy: string; classification: string; confidence: number;
  score_breakdown: Record<string, { points: number; max: number; why: string } | unknown>; risk_flags: string[]; explanation: string;
  ai_commentary: string | null; executed: boolean; rejected_reason: string | null; position_id: number | null; outcome: string | null; outcome_r: number | null;
};

export type Metrics = Record<string, number | null | string | Record<string, unknown>>;
