"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import ActivityList from "@/components/blocks/ActivityList";
import CalendarList from "@/components/blocks/CalendarList";
import MarketTable from "@/components/blocks/MarketTable";
import PositionsTable from "@/components/blocks/PositionsTable";
import { LineChart } from "@/components/charts";
import { useMe } from "@/components/Shell";
import { Empty, ErrorNote, Panel, PageHeader, SideChip, SignalChip, Stat, Toggle } from "@/components/ui";
import { post } from "@/lib/api";
import { lots, num, pct, price, signedUsd, time, tone, usd } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { Activity, EconEvent, Markets, Order, Overview, Position, Proposal } from "@/lib/types";

export default function Dashboard() {
  const me = useMe();
  const ov = usePoll<Overview>("/api/overview", 6000, ["positions"]);
  const pos = usePoll<Position[]>("/api/positions?status=open", 6000, ["positions"]);
  const ord = usePoll<Order[]>("/api/orders?status=open", 8000, ["positions"]);
  const mk = usePoll<Markets>("/api/markets", 15000, ["scanner"]);
  const props = usePoll<Proposal[]>("/api/analyst/proposals?limit=8", 20000, ["scanner"]);
  const cal = usePoll<{ events: EconEvent[] }>("/api/calendar?impact=High&days=2", 120000);
  const hist = usePoll<{ rows: Position[] }>("/api/trades?page_size=6", 30000, ["positions"]);
  const an = usePoll<{ equity_intraday: { t: string; equity: number }[] }>("/api/analytics", 60000);
  const act = usePoll<Activity[]>("/api/activity?limit=30", 30000);
  const [feed, setFeed] = useState<Activity[]>([]);
  const { subscribe } = useLive();
  useEffect(() => { if (act.data) setFeed(act.data); }, [act.data]);
  useEffect(() => subscribe((e) => { if (e.type === "activity") setFeed((f) => [e.data as Activity, ...f].slice(0, 40)); }), [subscribe]);
  const o = ov.data;
  const toggle = async (path: string, enabled: boolean) => { await post(path, { enabled }); ov.refresh(); };
  const curve = (an.data?.equity_intraday || []).map((p) => ({ t: Math.floor(new Date(p.t).getTime() / 1000), v: p.equity }));
  const upcoming = (cal.data?.events || []).filter((e) => new Date(e.time).getTime() > Date.now() - 3600_000);
  const gold = mk.data?.gold[0];
  const cr = Object.entries(o?.currency_risk || {}).filter(([, v]) => Math.abs(v) > 0.01).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title="Gold & Forex Dashboard" subtitle={o ? `${o.results_label} · account ${o.account_source}` : "Loading…"}
        right={o && me?.permissions.trade && (
          <div className="flex items-center gap-4 panel px-3 h-9">
            <label className="flex items-center gap-2 text-[12px] text-ink-2"><Toggle checked={o.config.scanning} onChange={(v) => toggle("/api/control/scanning", v)} label="scanning" />Market analysis</label>
            <label className="flex items-center gap-2 text-[12px] text-ink-2"><Toggle checked={o.config.auto_trading} disabled={o.config.kill_switch} onChange={(v) => toggle("/api/control/auto-trading", v)} label="auto trading" />Auto trading ({o.config.mode})</label>
          </div>)} />
      <ErrorNote error={ov.error} />
      {o?.agent.mode_problems && o.agent.mode_problems.length > 0 && <div className="text-[12px] text-warn bg-warn/8 border border-warn/25 rounded-md px-3 py-2 mb-3">Execution unavailable in {o.config.mode} mode: {o.agent.mode_problems.join("; ")}</div>}
      {o && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 2xl:grid-cols-8 gap-3">
            <Stat label="Balance" value={usd(o.balance)} sub={`start ${usd(o.starting_capital, 0)}`} />
            <Stat label="Equity" value={usd(o.equity)} sub={<span className={tone(o.unrealized_pnl)}>{signedUsd(o.unrealized_pnl)} open</span>} />
            <Stat label="Daily P&L" value={signedUsd(o.day_pnl)} tone={tone(o.day_pnl)} sub={pct(o.day_pnl_pct)} />
            <Stat label="Weekly P&L" value={signedUsd(o.week_pnl)} tone={tone(o.week_pnl)} sub={pct(o.week_pnl_pct)} />
            <Stat label="Monthly P&L" value={signedUsd(o.month_pnl)} tone={tone(o.month_pnl)} sub={pct(o.month_pnl_pct)} />
            <Stat label="Margin used" value={usd(o.margin_used)} sub={o.margin_level_pct ? `level ${num(o.margin_level_pct, 0)}%` : "no open margin"} />
            <Stat label="Exposure" value={o.effective_leverage == null ? "—" : `${num(o.effective_leverage, 2)}:1`} sub={`notional ${usd(o.notional_exposure, 0)}`} />
            <Stat label="Realised P&L" value={signedUsd(o.realized_pnl)} tone={tone(o.realized_pnl)} sub={`${o.total_trades} trades · win ${o.win_rate == null ? "—" : pct(o.win_rate, 1, false)}`} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Gold · XAU/USD" right={<Link href="/gold" className="text-[11.5px] text-accent">Open workspace →</Link>}>
              {gold ? (
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12.5px]">
                  <div className="col-span-2 flex items-baseline gap-3 mb-1"><span className="num text-[22px] font-semibold">{price(gold.mid, 2)}</span>
                    <span className="num text-mute">spread {gold.spread_pips?.toFixed(1)} pips</span></div>
                  <span className="text-mute">Session</span><span>{gold.session}</span>
                  <span className="text-mute">1h / 4h trend</span><span>{gold.trend_1h ?? "—"} / {gold.trend_4h ?? "—"}</span>
                  <span className="text-mute">USD strength</span><span className={`num ${tone(-(mk.data?.strength?.USD ?? 0))}`}>{mk.data?.strength?.USD == null ? "—" : pct(mk.data.strength.USD, 2)}</span>
                  <span className="text-mute">US 10Y yield</span><span className="num">{mk.data?.us10y ? `${mk.data.us10y.value.toFixed(2)}% (${mk.data.us10y.trend})` : "—"}</span>
                  <span className="text-mute">Asian range</span><span className="num">{gold.levels?.asia_low ? `${price(gold.levels.asia_low, 2)} – ${price(gold.levels.asia_high, 2)}` : "—"}</span>
                  <span className="text-mute">Signal</span><span className="flex gap-1">{gold.direction && <SideChip side={gold.direction} />}<SignalChip value={gold.signal} /></span>
                  {!gold.data_ok && <span className="col-span-2 text-[11px] text-warn mt-1">{gold.data_issues[0]}</span>}
                </div>) : <Empty>Waiting for the first analysis cycle…</Empty>}
            </Panel>
            <Panel title="Forex" className="xl:col-span-2" pad={false} right={<Link href="/markets" className="text-[11.5px] text-accent">All markets →</Link>}>
              <MarketTable rows={mk.data?.forex || []} compact />
            </Panel>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Active positions" className="xl:col-span-2" pad={false}><PositionsTable rows={pos.data || []} onChange={() => { pos.refresh(); ov.refresh(); }} compact /></Panel>
            <Panel title="Risk exposure" right={<span className={`chip ${o.trading_allowed ? "bg-up/10 text-up border-up/25" : "bg-down/12 text-down border-down/30"}`}>{o.trading_allowed ? "NEW TRADES ALLOWED" : "NEW TRADES BLOCKED"}</span>}>
              <ul className="space-y-1">
                {o.gates.map((g) => (
                  <li key={g.name} className="flex items-start gap-2 text-[12px]">
                    <span className={`mt-[5px] w-[6px] h-[6px] rounded-full shrink-0 ${g.passed ? "bg-up" : "bg-down"}`} />
                    <span className="text-ink-2 w-[128px] shrink-0">{g.name.replace(/_/g, " ")}</span><span className="text-mute num text-[11.5px]">{g.detail}</span>
                  </li>))}
              </ul>
              <div className="label mt-3 mb-1">Net risk by currency</div>
              {cr.length ? cr.map(([c, v]) => <div key={c} className="flex justify-between text-[12px] num"><span>{c}</span><span className={tone(v)}>{v > 0 ? "long" : "short"} {usd(Math.abs(v))}</span></div>)
                : <div className="text-[11.5px] text-mute">No open currency risk.</div>}
            </Panel>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Trading signals (AI analyst)" className="xl:col-span-2" pad={false} right={<Link href="/analyst" className="text-[11.5px] text-accent">All proposals →</Link>}>
              {(props.data || []).length ? (
                <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Time</th><th>Instrument</th><th>Side</th><th>Classification</th><th className="text-right">Conf.</th>
                  <th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target</th><th className="text-right">Lots</th><th>Outcome</th></tr></thead>
                  <tbody>{props.data!.map((p) => <tr key={p.id}><td className="num text-ink-2">{time(p.ts)}</td><td className="font-semibold">{p.display}</td>
                    <td><SideChip side={p.direction} /></td><td><SignalChip value={p.classification} /></td><td className="num text-right">{p.confidence}</td>
                    <td className="num text-right">{price(p.entry, p.digits)}</td><td className="num text-right text-down">{price(p.stop_loss, p.digits)}</td>
                    <td className="num text-right text-up">{price(p.take_profit, p.digits)}</td><td className="num text-right">{lots(p.lots)}</td>
                    <td className="text-[11.5px] max-w-[220px] truncate" title={p.rejected_reason || ""}>{p.executed ? <span className="text-up">executed</span> : <span className="text-mute">{p.rejected_reason || "—"}</span>}</td></tr>)}</tbody></table></div>
              ) : <Empty>No trade proposals yet. The analyst records every proposal, including the ones it rejects.</Empty>}
            </Panel>
            <Panel title="High-impact events (48h)" right={<Link href="/calendar" className="text-[11.5px] text-accent">Calendar →</Link>}>
              <div className="max-h-[300px] overflow-y-auto -my-2"><CalendarList events={upcoming} max={12} compact /></div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
            <Panel title="Equity curve" right={<Link href="/analytics" className="text-[11.5px] text-accent">Performance →</Link>}>
              {curve.length > 1 ? <LineChart points={curve} height={200} color={curve[curve.length - 1].v >= curve[0].v ? "up" : "down"} /> : <div className="h-[200px] grid place-items-center text-[12px] text-mute">Equity history builds as ATLAS runs.</div>}
            </Panel>
            <Panel title={`Pending orders (${(ord.data || []).length})`} pad={false}>
              {(ord.data || []).length ? (<table className="tbl"><thead><tr><th>Instrument</th><th>Order</th><th className="text-right">Lots</th><th className="text-right">Price</th></tr></thead>
                <tbody>{ord.data!.map((x) => <tr key={x.id}><td>{x.display}</td><td className={x.purpose === "stop" ? "text-down" : x.purpose.startsWith("tp") ? "text-up" : ""}>{x.side.toUpperCase()} {x.type} · {x.purpose}</td>
                  <td className="num text-right">{lots(x.lots - x.filled_lots)}</td><td className="num text-right">{price(x.limit_price ?? x.stop_price)}</td></tr>)}</tbody></table>) : <Empty>No working orders.</Empty>}
            </Panel>
            <Panel title="Recent trades" pad={false} right={<Link href="/history" className="text-[11.5px] text-accent">Journal →</Link>}>
              {(hist.data?.rows || []).length ? (<table className="tbl"><tbody>{hist.data!.rows.map((t) => <tr key={t.id}><td>{t.display}</td><td><SideChip side={t.side} /></td>
                <td className="num text-right">{lots(t.initial_lots)}</td><td className={`num text-right ${tone(t.net_pnl)}`}>{signedUsd(t.net_pnl)}</td></tr>)}</tbody></table>) : <Empty>No closed trades yet.</Empty>}
            </Panel>
          </div>
          <Panel title="Activity" className="mt-3" right={<Link href="/activity" className="text-[11.5px] text-accent">Full feed →</Link>}>
            <div className="max-h-[300px] overflow-y-auto -my-2"><ActivityList rows={feed.slice(0, 20)} dense /></div>
          </Panel>
        </>
      )}
    </div>
  );
}
