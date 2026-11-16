"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import ActivityList from "@/components/blocks/ActivityList";
import PositionsTable from "@/components/blocks/PositionsTable";
import { LineChart } from "@/components/charts";
import { useMe } from "@/components/Shell";
import { ErrorNote, Panel, PageHeader, Stat, Toggle } from "@/components/ui";
import { post } from "@/lib/api";
import { compact, num, pct, signedUsd, tone, usd } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { Activity, Overview, Position } from "@/lib/types";

export default function OverviewPage() {
  const me = useMe();
  const ov = usePoll<Overview>("/api/overview", 6000, ["positions"]);
  const pos = usePoll<Position[]>("/api/positions?status=open", 6000, ["positions"]);
  const an = usePoll<{ equity_intraday: { t: string; equity: number }[] }>("/api/analytics", 60000);
  const act = usePoll<Activity[]>("/api/activity?limit=40", 30000);
  const [feed, setFeed] = useState<Activity[]>([]);
  const { subscribe } = useLive();
  useEffect(() => { if (act.data) setFeed(act.data); }, [act.data]);
  useEffect(() => subscribe((e) => { if (e.type === "activity") setFeed((f) => [e.data as Activity, ...f].slice(0, 60)); }), [subscribe]);

  const o = ov.data;
  const toggle = async (path: string, enabled: boolean) => { await post(path, { enabled }); ov.refresh(); };
  const curve = (an.data?.equity_intraday || []).map((p) => ({ t: Math.floor(new Date(p.t).getTime() / 1000), v: p.equity }));

  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader title="Portfolio Overview" subtitle={o ? o.results_label : "Loading…"}
        right={o && me?.permissions.trade && (
          <div className="flex items-center gap-4 panel px-3 h-9">
            <label className="flex items-center gap-2 text-[12px] text-ink-2"><Toggle checked={o.config.scanning} onChange={(v) => toggle("/api/control/scanning", v)} label="scanning" />Market scanning</label>
            <label className="flex items-center gap-2 text-[12px] text-ink-2"><Toggle checked={o.config.auto_paper} disabled={o.config.kill_switch} onChange={(v) => toggle("/api/control/auto-paper", v)} label="auto paper" />Auto paper trading</label>
          </div>
        )} />
      <ErrorNote error={ov.error} />
      {o && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
            <Stat label="Portfolio value" value={usd(o.equity)} sub={`start ${usd(o.starting_capital, 0)}`} />
            <Stat label="Available capital" value={usd(o.available_capital)} sub={`${num((o.positions_value / Math.max(o.equity, 1)) * 100, 1)}% deployed`} />
            <Stat label="Open positions" value={o.open_positions} sub={`max ${o.gates.find((g) => g.name === "max_open_positions")?.detail.split("/")[1] ?? "3"}`} />
            <Stat label="Realised P&L" value={signedUsd(o.realized_pnl)} tone={tone(o.realized_pnl)} sub={`fees ${usd(o.fees_paid)}`} />
            <Stat label="Unrealised P&L" value={signedUsd(o.unrealized_pnl)} tone={tone(o.unrealized_pnl)} />
            <Stat label="Daily P&L" value={signedUsd(o.day_pnl)} tone={tone(o.day_pnl)} sub={pct(o.day_pnl_pct)} />
            <Stat label="Weekly P&L" value={signedUsd(o.week_pnl)} tone={tone(o.week_pnl)} sub={pct(o.week_pnl_pct)} />
            <Stat label="Monthly P&L" value={signedUsd(o.month_pnl)} tone={tone(o.month_pnl)} sub={pct(o.month_pnl_pct)} />
            <Stat label="Win rate" value={o.win_rate == null ? "—" : pct(o.win_rate, 1, false)} sub={`${o.wins}W / ${o.losses}L`} />
            <Stat label="Profit factor" value={o.profit_factor == null ? "—" : num(o.profit_factor, 2)} sub={o.profit_factor_note || "gross win / gross loss"} />
            <Stat label="Max drawdown" value={pct(o.max_drawdown_pct, 2, false)} tone={o.max_drawdown_pct < 0 ? "text-down" : ""} />
            <Stat label="Total trades" value={o.total_trades} sub={o.expectancy_r != null ? `expectancy ${num(o.expectancy_r, 2)}R` : "closed trades"} />
            <Stat label="Avg winning trade" value={o.avg_win == null ? "—" : signedUsd(o.avg_win)} tone="text-up" />
            <Stat label="Avg losing trade" value={o.avg_loss == null ? "—" : signedUsd(o.avg_loss)} tone="text-down" />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Equity curve" className="xl:col-span-2" right={<span className="text-[11px] text-mute">paper account · 1-min snapshots</span>}>
              {curve.length > 1 ? <LineChart points={curve} height={260} color={curve[curve.length - 1].v >= curve[0].v ? "up" : "down"} />
                : <div className="h-[260px] grid place-items-center text-[12px] text-mute">Equity history builds as the agent runs (snapshot every minute).</div>}
            </Panel>
            <Panel title="Risk gates" right={<span className={`chip ${o.trading_allowed ? "bg-up/10 text-up border-up/25" : "bg-down/12 text-down border-down/30"}`}>{o.trading_allowed ? "NEW TRADES ALLOWED" : "NEW TRADES BLOCKED"}</span>}>
              <ul className="space-y-1.5">
                {o.gates.map((g) => (
                  <li key={g.name} className="flex items-start gap-2 text-[12px]">
                    <span className={`mt-[5px] w-[6px] h-[6px] rounded-full shrink-0 ${g.passed ? "bg-up" : "bg-down"}`} />
                    <span className="text-ink-2 w-[140px] shrink-0">{g.name.replace(/_/g, " ")}</span>
                    <span className="text-mute num text-[11.5px]">{g.detail}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 pt-3 border-t border-line text-[11.5px] text-mute">
                Risk per trade {o.config.risk_per_trade_pct}% · <Link href="/settings" className="text-accent hover:underline">adjust limits</Link>
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Active positions" className="xl:col-span-2" pad={false} right={<Link href="/terminal" className="text-[11.5px] text-accent">Open terminal →</Link>}>
              <PositionsTable rows={pos.data || []} onChange={() => { pos.refresh(); ov.refresh(); }} compact />
            </Panel>
            <Panel title="AI activity" right={<Link href="/activity" className="text-[11.5px] text-accent">Full feed →</Link>}>
              <div className="max-h-[380px] overflow-y-auto -my-2"><ActivityList rows={feed.slice(0, 25)} dense /></div>
            </Panel>
          </div>
          {o.agent.last_error && <p className="text-[11px] text-warn mt-3 num">Agent warning: {o.agent.last_error.slice(0, 200)}</p>}
        </>
      )}
    </div>
  );
}
