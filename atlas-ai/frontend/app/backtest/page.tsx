"use client";
import { useEffect, useState } from "react";
import { LineChart } from "@/components/charts";
import { useMe } from "@/components/Shell";
import { Chip, Empty, ErrorNote, Panel, PageHeader, Stat, Toggle } from "@/components/ui";
import { api, post } from "@/lib/api";
import { duration, num, pair, pct, price, signedUsd, tone } from "@/lib/format";
import { usePoll } from "@/lib/live";

type M = Record<string, any>;
type Run = { id: number; created_at: string; status: string; params: M; metrics: M; oos_metrics: M; error: string | null };
type Detail = Run & { walk_forward: M; equity_curve: { t: number; equity: number }[]; trades: M[]; data_quality: M; disclaimer: string };

const STRATS = ["trend_following", "momentum", "breakout", "vwap_reversion"];
const iso = (d: Date) => d.toISOString().slice(0, 16);

function MetricRow({ label, a, b, fmt }: { label: string; a: unknown; b?: unknown; fmt: (v: any) => string }) {
  return <tr><td className="text-ink-2">{label}</td><td className="num text-right">{fmt(a)}</td>{b !== undefined && <td className="num text-right">{fmt(b)}</td>}</tr>;
}

export default function Backtest() {
  const me = useMe();
  const runs = usePoll<Run[]>("/api/backtests", 4000);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [cmp, setCmp] = useState<number[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const now = new Date();
  const [f, setF] = useState({ symbol: "SOLUSDC", strategy: "momentum", timeframe: "5m", start: iso(new Date(now.getTime() - 30 * 864e5)), end: iso(now),
    starting_capital: 10000, taker_fee_bps: 10, maker_fee_bps: 10, base_slippage_bps: 2, spread_bps: 2, risk_per_trade_pct: 0.5, oos_fraction: 0.3, walk_forward: true, folds: 3 });
  const upd = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (sel == null) return;
    const r = runs.data?.find((x) => x.id === sel);
    api<Detail>(`/api/backtests/${sel}`).then(setDetail).catch((e) => setErr(e.message));
    if (r && r.status !== "done" && r.status !== "failed") { const id = setInterval(() => api<Detail>(`/api/backtests/${sel}`).then(setDetail), 3000); return () => clearInterval(id); }
  }, [sel, runs.data?.find((x) => x.id === sel)?.status]); // eslint-disable-line

  const submit = async () => {
    setErr(null);
    try {
      const r = await post<{ id: number }>("/api/backtests", { ...f, symbol: f.symbol.toUpperCase(), start: new Date(f.start).toISOString(), end: new Date(f.end).toISOString() });
      runs.refresh(); setSel(r.id);
    } catch (e) { setErr((e as Error).message); }
  };
  const m = detail?.metrics || {};
  const o = detail?.oos_metrics || {};
  const ins = m.in_sample || {};
  const wf = detail?.walk_forward || {};
  const curve = (detail?.equity_curve || []).map((p) => ({ t: Math.floor(p.t / 1000), v: p.equity }));
  const field = (k: string, label: string, type = "number", step?: string) => (
    <label className="block"><span className="label block mb-1">{label}</span>
      <input className="input w-full" type={type} step={step} value={(f as M)[k]} onChange={(e) => upd(k, type === "number" ? Number(e.target.value) : e.target.value)} /></label>);
  const cmpRuns = (runs.data || []).filter((r) => cmp.includes(r.id) && r.status === "done");

  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title="Backtesting" subtitle="Historical simulation on Binance candles · next-bar-open fills · fees, spread and slippage modelled · in/out-of-sample and walk-forward" />
      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-3">
        <div className="flex flex-col gap-3">
          <Panel title="New backtest">
            <div className="grid grid-cols-2 gap-3">
              {field("symbol", "Symbol", "text")}
              <label className="block"><span className="label block mb-1">Strategy</span>
                <select className="input w-full" value={f.strategy} onChange={(e) => upd("strategy", e.target.value)}>{STRATS.map((s) => <option key={s}>{s}</option>)}</select></label>
              <label className="block"><span className="label block mb-1">Timeframe</span>
                <select className="input w-full" value={f.timeframe} onChange={(e) => upd("timeframe", e.target.value)}>{["1m", "5m", "15m", "1h", "4h"].map((s) => <option key={s}>{s}</option>)}</select></label>
              {field("starting_capital", "Capital (USDC)")}
              <div className="col-span-2 grid grid-cols-2 gap-3">{field("start", "Start (UTC)", "datetime-local")}{field("end", "End (UTC)", "datetime-local")}</div>
              {field("taker_fee_bps", "Taker fee bps", "number", "0.5")}{field("maker_fee_bps", "Maker fee bps", "number", "0.5")}
              {field("base_slippage_bps", "Slippage bps", "number", "0.5")}{field("spread_bps", "Spread bps", "number", "0.5")}
              {field("risk_per_trade_pct", "Risk / trade %", "number", "0.1")}{field("oos_fraction", "Out-of-sample", "number", "0.05")}
              <label className="flex items-center gap-2 text-[12px] text-ink-2 col-span-2"><Toggle checked={f.walk_forward} onChange={(v) => upd("walk_forward", v)} />Walk-forward optimisation ({f.folds} folds)</label>
            </div>
            <ErrorNote error={err} />
            <button className="btn btn-primary w-full justify-center mt-3" onClick={submit} disabled={!me?.permissions.trade}>Run backtest</button>
          </Panel>
          <Panel title="Runs" pad={false} right={cmp.length > 1 && <Chip tone="accent">{cmp.length} selected</Chip>}>
            <div className="max-h-[520px] overflow-y-auto">
              {(runs.data || []).map((r) => (
                <div key={r.id} onClick={() => setSel(r.id)} className={`px-4 py-2.5 border-b border-line/60 cursor-pointer ${sel === r.id ? "bg-accent/10" : "hover:bg-white/[0.02]"}`}>
                  <div className="flex items-center gap-2">
                    <input type="checkbox" checked={cmp.includes(r.id)} onClick={(e) => e.stopPropagation()} onChange={(e) => setCmp((c) => (e.target.checked ? [...c, r.id] : c.filter((x) => x !== r.id)))} />
                    <span className="text-[12.5px] font-semibold">#{r.id} {pair(r.params.symbol)} · {r.params.strategy}</span>
                    <span className="flex-1" />
                    <Chip tone={r.status === "done" ? "up" : r.status === "failed" ? "down" : "warn"}>{r.status.toUpperCase()}</Chip>
                  </div>
                  <div className="text-[11px] text-mute mt-0.5 num">{r.params.timeframe} · {r.params.start?.slice(0, 10)} → {r.params.end?.slice(0, 10)}
                    {r.status === "done" && <> · <span className={tone(r.metrics.net_return_pct)}>{pct(r.metrics.net_return_pct)}</span> · {r.metrics.total_trades} trades</>}</div>
                </div>))}
              {!runs.data?.length && <Empty>No backtests yet.</Empty>}
            </div>
          </Panel>
        </div>
        <div className="flex flex-col gap-3 min-w-0">
          {cmpRuns.length > 1 && (
            <Panel title="Strategy comparison" pad={false}>
              <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Run</th><th className="text-right">Net return</th><th className="text-right">OOS return</th><th className="text-right">Trades</th>
                <th className="text-right">Win %</th><th className="text-right">PF</th><th className="text-right">Exp. R</th><th className="text-right">Max DD</th><th className="text-right">Sharpe</th><th className="text-right">WF OOS exp.</th></tr></thead>
                <tbody>{cmpRuns.map((r) => <tr key={r.id}><td>#{r.id} {pair(r.params.symbol)} {r.params.strategy} {r.params.timeframe}</td>
                  <td className={`num text-right ${tone(r.metrics.net_return_pct)}`}>{pct(r.metrics.net_return_pct)}</td><td className={`num text-right ${tone(r.oos_metrics.net_return_pct)}`}>{pct(r.oos_metrics.net_return_pct)}</td>
                  <td className="num text-right">{r.metrics.total_trades}</td><td className="num text-right">{pct(r.metrics.win_rate, 1, false)}</td><td className="num text-right">{num(r.metrics.profit_factor, 2)}</td>
                  <td className={`num text-right ${tone(r.metrics.expectancy_r)}`}>{num(r.metrics.expectancy_r, 3)}</td><td className="num text-right text-down">{pct(r.metrics.max_drawdown_pct, 2, false)}</td>
                  <td className="num text-right">{num(r.metrics.sharpe, 2)}</td><td className="num text-right">—</td></tr>)}</tbody></table></div>
            </Panel>)}
          {!detail ? <Panel><Empty>Run or select a backtest to see results.</Empty></Panel> : detail.status !== "done" ? (
            <Panel title={`Backtest #${detail.id}`}>{detail.status === "failed" ? <ErrorNote error={detail.error} /> : <div className="text-[12.5px] text-ink-2">{detail.status === "fetching" ? "Downloading historical candles from Binance…" : "Simulating…"} this can take up to a minute with walk-forward enabled.</div>}</Panel>
          ) : (
            <>
              <div className="text-[11.5px] text-warn bg-warn/8 border border-warn/25 rounded-md px-3 py-2">BACKTEST — {detail.disclaimer}</div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <Stat label="Net return" value={pct(m.net_return_pct)} tone={tone(m.net_return_pct)} sub={signedUsd(m.final_equity - detail.params.starting_capital)} />
                <Stat label="Win rate" value={pct(m.win_rate, 1, false)} sub={`${m.wins}W / ${m.losses}L`} />
                <Stat label="Profit factor" value={num(m.profit_factor, 2)} />
                <Stat label="Max drawdown" value={pct(m.max_drawdown_pct, 2, false)} tone="text-down" />
                <Stat label="Trades" value={m.total_trades} sub={`${m.signals} signals · ${m.rejected_by_risk} rejected`} />
                <Stat label="Sharpe (ann.)" value={num(m.sharpe, 2)} /><Stat label="Sortino (ann.)" value={num(m.sortino, 2)} />
                <Stat label="Expectancy" value={`${num(m.expectancy_r, 3)}R`} tone={tone(m.expectancy_r)} sub={signedUsd(m.expectancy)} />
                <Stat label="Avg trade return" value={pct(m.avg_trade_return_pct, 3)} tone={tone(m.avg_trade_return_pct)} />
                <Stat label="Avg holding" value={duration((m.avg_holding_minutes || 0) * 60)} sub={`exposure ${num(m.exposure_pct, 1)}%`} />
              </div>
              <Panel title={`Equity · #${detail.id} ${pair(detail.params.symbol)} ${detail.params.strategy} ${detail.params.timeframe}`} right={<span className="text-[11px] text-mute num">fees {signedUsd(-m.fees)} · slippage {signedUsd(-m.slippage_cost)}</span>}>
                {curve.length > 1 ? <LineChart points={curve} height={260} color={m.net_return_pct >= 0 ? "up" : "down"} /> : <Empty>No equity data.</Empty>}
              </Panel>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                <Panel title="In-sample vs out-of-sample" pad={false}>
                  <table className="tbl"><thead><tr><th>Metric</th><th className="text-right">In-sample</th><th className="text-right">Out-of-sample ({Math.round(detail.params.oos_fraction * 100)}%)</th></tr></thead>
                    <tbody>
                      <MetricRow label="Trades" a={ins.total_trades} b={o.total_trades} fmt={(v) => String(v ?? "—")} />
                      <MetricRow label="Net return" a={ins.net_return_pct} b={o.net_return_pct} fmt={(v) => pct(v)} />
                      <MetricRow label="Win rate" a={ins.win_rate} b={o.win_rate} fmt={(v) => pct(v, 1, false)} />
                      <MetricRow label="Profit factor" a={ins.profit_factor} b={o.profit_factor} fmt={(v) => num(v, 2)} />
                      <MetricRow label="Expectancy (R)" a={ins.expectancy_r} b={o.expectancy_r} fmt={(v) => num(v, 3)} />
                      <MetricRow label="Max drawdown" a={ins.max_drawdown_pct} b={o.max_drawdown_pct} fmt={(v) => pct(v, 2, false)} />
                    </tbody></table>
                </Panel>
                <Panel title="Walk-forward evaluation" pad={false} right={wf.walk_forward_efficiency != null && <span className="text-[11px] text-mute">efficiency {num(wf.walk_forward_efficiency, 2)}</span>}>
                  {wf.folds ? <>
                    <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Fold</th><th>Params (chosen in-sample)</th><th className="text-right">Train exp. R</th><th className="text-right">Test trades</th><th className="text-right">Test exp. R</th><th className="text-right">Test return</th></tr></thead>
                      <tbody>{wf.folds.map((x: M) => <tr key={x.fold}><td>{x.fold}</td><td className="num text-[11px] text-ink-2">{JSON.stringify(x.params)}</td>
                        <td className="num text-right">{num(x.train_metrics.expectancy_r, 3)}</td><td className="num text-right">{x.test_metrics.total_trades}</td>
                        <td className={`num text-right ${tone(x.test_metrics.expectancy_r)}`}>{num(x.test_metrics.expectancy_r, 3)}</td><td className={`num text-right ${tone(x.test_metrics.net_return_pct)}`}>{pct(x.test_metrics.net_return_pct)}</td></tr>)}</tbody></table></div>
                    <div className="px-4 py-2 text-[11px] text-mute border-t border-line">Aggregate unseen-data result: {wf.oos_aggregate.total_trades} trades, expectancy {num(wf.oos_aggregate.expectancy_r, 3)}R, net {signedUsd(wf.oos_aggregate.net_pnl)}. {wf.note}</div>
                  </> : <Empty>Walk-forward disabled for this run.</Empty>}
                </Panel>
              </div>
              <Panel title={`Trades (${detail.trades.length})`} pad={false}>
                <div className="overflow-x-auto max-h-[420px]"><table className="tbl"><thead><tr><th>Entry</th><th>Exit</th><th className="text-right">Entry px</th><th className="text-right">Exit px</th>
                  <th className="text-right">Fees</th><th className="text-right">Net</th><th className="text-right">R</th><th>Exit reason</th></tr></thead>
                  <tbody>{detail.trades.slice().reverse().map((t, i) => <tr key={i}><td className="num text-ink-2">{new Date(t.entry_time).toISOString().slice(5, 16).replace("T", " ")}</td>
                    <td className="num text-ink-2">{new Date(t.exit_time).toISOString().slice(5, 16).replace("T", " ")}</td><td className="num text-right">{price(t.entry)}</td><td className="num text-right">{price(t.exit)}</td>
                    <td className="num text-right text-ink-2">{num(t.fees, 2)}</td><td className={`num text-right ${tone(t.net_pnl)}`}>{signedUsd(t.net_pnl)}</td>
                    <td className={`num text-right ${tone(t.r_multiple)}`}>{num(t.r_multiple, 2)}</td><td className="text-ink-2 max-w-[340px] truncate" title={t.exit_reason}>{t.exit_reason}</td></tr>)}</tbody></table></div>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
