"use client";
import Link from "next/link";
import { useState } from "react";
import { Bars, LineChart } from "@/components/charts";
import { Empty, ErrorNote, Panel, PageHeader, Stat, Tabs } from "@/components/ui";
import { num, pct, signedUsd, tone, usd } from "@/lib/format";
import { usePoll } from "@/lib/live";

type Grp = { key: string; total_trades: number; win_rate: number | null; profit_factor: number | null; net_pnl: number; expectancy_r?: number | null; fees: number; slippage: number };
type A = {
  label: string; equity_intraday: { t: string; equity: number }[]; equity_daily: { t: string; equity: number }[]; equity_weekly: { t: string; equity: number }[];
  equity_monthly: { t: string; equity: number }[]; drawdown: { t: string; dd: number }[]; max_drawdown_pct: number; by_strategy: Grp[]; by_asset: Grp[];
  by_session: Grp[]; r_distribution: number[]; fees_total: number; slippage_total: number; totals: Record<string, number | null>;
};
type Cal = { buckets: { bucket: string; trades: number; win_rate: number | null; avg_r: number | null; note: string }[]; note: string };

const ts = (t: string) => Math.floor(new Date(t.length <= 7 ? t + "-01" : t).getTime() / 1000);

function GroupTable({ rows, label }: { rows: Grp[]; label: string }) {
  if (!rows.length) return <Empty>No closed trades yet.</Empty>;
  return (
    <table className="tbl"><thead><tr><th>{label}</th><th className="text-right">Trades</th><th className="text-right">Win %</th><th className="text-right">PF</th>
      <th className="text-right">Exp. R</th><th className="text-right">Fees</th><th className="text-right">Net P&L</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.key}><td>{r.key}</td><td className="num text-right">{r.total_trades}</td><td className="num text-right">{r.win_rate == null ? "—" : pct(r.win_rate, 1, false)}</td>
          <td className="num text-right">{num(r.profit_factor, 2)}</td><td className={`num text-right ${tone(r.expectancy_r)}`}>{num(r.expectancy_r, 2)}</td>
          <td className="num text-right text-ink-2">{usd(r.fees)}</td><td className={`num text-right ${tone(r.net_pnl)}`}>{signedUsd(r.net_pnl)}</td></tr>))}</tbody></table>
  );
}

export default function Analytics() {
  const [mode, setMode] = useState<"paper" | "demo" | "live">("paper");
  const [period, setPeriod] = useState<"intraday" | "daily" | "weekly" | "monthly">("intraday");
  const { data, error } = usePoll<A>(`/api/analytics?mode=${mode}`, 30000);
  const cal = usePoll<Cal>("/api/analyst/calibration", 60000);
  const curve = data ? (period === "intraday" ? data.equity_intraday : data[`equity_${period}`]).map((p) => ({ t: ts(p.t), v: p.equity })) : [];
  const dd = (data?.drawdown || []).map((p) => ({ t: ts(p.t), v: p.dd }));
  const buckets = [-1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5, 3];
  const dist = buckets.map((b, i) => (data?.r_distribution || []).filter((r) => r >= b && (i === buckets.length - 1 || r < buckets[i + 1])).length);
  const t = data?.totals || {};
  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader title="Performance Analytics" subtitle={data?.label}
        right={<Tabs value={mode} onChange={setMode} options={[{ value: "paper", label: "Paper" }, { value: "demo", label: "Demo account" }, { value: "live", label: "Live account" }]} />} />
      <div className="text-[11.5px] text-mute -mt-2 mb-3">Paper, demo, live and backtested results are tracked separately and never combined. Backtests live under <Link href="/backtest" className="text-accent">Backtesting</Link>.</div>
      <ErrorNote error={error} />
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Stat label="Trades" value={t.total_trades ?? 0} /><Stat label="Win rate" value={t.win_rate == null ? "—" : pct(t.win_rate as number, 1, false)} />
        <Stat label="Profit factor" value={num(t.profit_factor as number, 2)} /><Stat label="Expectancy" value={t.expectancy_r == null ? "—" : `${num(t.expectancy_r as number, 2)}R`} tone={tone(t.expectancy_r as number)} />
        <Stat label="Net P&L" value={signedUsd(t.net_pnl as number)} tone={tone(t.net_pnl as number)} /><Stat label="Max drawdown" value={pct(data?.max_drawdown_pct, 2, false)} tone="text-down" />
        <Stat label="Fees paid" value={usd(data?.fees_total)} /><Stat label="Slippage cost" value={usd(data?.slippage_total)} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        <Panel title="Equity curve" className="xl:col-span-2" right={<Tabs value={period} onChange={setPeriod} options={[{ value: "intraday", label: "1m" }, { value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" }, { value: "monthly", label: "Monthly" }]} />}>
          {curve.length > 1 ? <LineChart points={curve} height={280} /> : <div className="h-[280px] grid place-items-center text-[12px] text-mute">Not enough history yet for this period.</div>}
        </Panel>
        <Panel title="Win / loss distribution (R multiples)">
          {data?.r_distribution.length ? <Bars values={dist.map((v, i) => (buckets[i] < 0 ? -v : v))} labels={buckets.map((b) => `${b}R`)} height={240} /> : <Empty>No closed trades yet.</Empty>}
        </Panel>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        <Panel title="Drawdown history" className="xl:col-span-2">{dd.length > 1 ? <LineChart points={dd} height={200} color="down" percent /> : <Empty>No drawdown history yet.</Empty>}</Panel>
        <Panel title="Confidence calibration" right={<span className="text-[10.5px] text-mute">measured outcomes</span>}>
          <table className="tbl"><thead><tr><th>Score</th><th className="text-right">Trades</th><th className="text-right">Win %</th><th className="text-right">Avg R</th></tr></thead>
            <tbody>{(cal.data?.buckets || []).map((b) => <tr key={b.bucket}><td>{b.bucket}</td><td className="num text-right">{b.trades}</td>
              <td className="num text-right">{b.win_rate == null ? "—" : pct(b.win_rate, 1, false)}</td><td className={`num text-right ${tone(b.avg_r)}`}>{num(b.avg_r, 2)}</td></tr>)}</tbody></table>
          <p className="text-[11px] text-mute mt-3 leading-snug">{cal.data?.note} Buckets with fewer than 20 trades are not statistically meaningful.</p>
        </Panel>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        <Panel title="Strategy comparison" pad={false}><GroupTable rows={data?.by_strategy || []} label="Strategy" /></Panel>
        <Panel title="Performance by instrument (gold & forex)" pad={false}><GroupTable rows={data?.by_asset || []} label="Instrument" /></Panel>
        <Panel title="Performance by session" pad={false}><GroupTable rows={data?.by_session || []} label="Session (UTC)" /></Panel>
      </div>
    </div>
  );
}
