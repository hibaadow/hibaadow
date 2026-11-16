"use client";
import { useMemo, useState } from "react";
import ChartPanel, { type TF } from "@/components/blocks/ChartPanel";
import PositionPanel from "@/components/blocks/PositionPanel";
import ProposalCard from "@/components/blocks/ProposalCard";
import CalendarList from "@/components/blocks/CalendarList";
import { LineChart, type Level } from "@/components/charts";
import { Chip, Empty, KV, Panel, PageHeader, SideChip, SignalChip } from "@/components/ui";
import { num, pct, price, tone } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { EconEvent, MarketRow, Position, Proposal, US10Y } from "@/lib/types";

type Gold = { row: MarketRow | null; usd_strength: number | null; strength: Record<string, number>; us10y: US10Y | null; usd_events: EconEvent[];
  decisions: Proposal[]; session: { active: string[]; label: string; overlap: boolean; market_open: boolean; rollover: boolean };
  spec: { contract_size: number; pip_size: number; digits: number; min_lot: number; pip_value_usd_per_lot: number; margin_rate: number } };

export default function GoldWorkspace() {
  const [tf, setTf] = useState<TF>("5m");
  const g = usePoll<Gold>("/api/gold", 15000, ["scanner"]);
  const pos = usePoll<Position[]>("/api/positions?status=open", 6000, ["positions"]);
  const { quotes } = useLive();
  const p = pos.data?.find((x) => x.symbol === "XAUUSD");
  const row = g.data?.row;
  const q = quotes.XAUUSD ?? (row?.bid != null && row?.ask != null ? { bid: row.bid, ask: row.ask, ts: 0 } : undefined);
  const lv = row?.levels;
  const levels: Level[] = useMemo(() => {
    const out: Level[] = [];
    if (lv?.asia_high) out.push({ price: lv.asia_high, label: "ASIA H", color: "warn" });
    if (lv?.asia_low) out.push({ price: lv.asia_low, label: "ASIA L", color: "warn" });
    if (lv?.prev_day_high) out.push({ price: lv.prev_day_high, label: "PDH", color: "accent" });
    if (lv?.prev_day_low) out.push({ price: lv.prev_day_low, label: "PDL", color: "accent" });
    if (p) out.push({ price: p.entry_price, label: "ENTRY", color: "accent" }, { price: p.stop_price, label: "SL", color: "down" }, { price: p.tp1, label: "TP1", color: "up" },
      ...(p.tp2 ? [{ price: p.tp2, label: "TP2", color: "up" as const }] : []));
    return out;
  }, [lv, p]);
  const y = g.data?.us10y;
  const usd = g.data?.usd_strength;
  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title="XAU/USD · Gold Workspace"
        subtitle={<>Bid <span className="num text-ink">{price(q?.bid, 2)}</span> · Ask <span className="num text-ink">{price(q?.ask, 2)}</span>
          {q && <> · spread <span className="num">{((q.ask - q.bid) / 0.1).toFixed(1)} pips</span></>} · {g.data?.session.label ?? "—"}
          {g.data && !g.data.session.market_open && <span className="text-warn"> · market closed</span>}{g.data?.session.rollover && <span className="text-warn"> · rollover</span>}</>}
        right={row && <span className="flex items-center gap-2">{row.direction && <SideChip side={row.direction} />}<SignalChip value={row.signal} /><span className="num text-[12px] text-ink-2">conf {row.confidence || "—"}</span></span>} />
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-3">
        <ChartPanel symbol="XAUUSD" tf={tf} onTf={setTf} levels={levels} />
        <div className="flex flex-col gap-3">
          {p && <PositionPanel pos={p} />}
          <Panel title="Gold analysis">
            {row ? <>
              <KV k="Session" v={<span>{g.data?.session.overlap ? <Chip tone="up">LONDON/NY OVERLAP</Chip> : g.data?.session.label}</span>} />
              <KV k="Trend 1h / 4h" v={`${row.trend_1h ?? "—"} / ${row.trend_4h ?? "—"}`} />
              <KV k="Market structure (5m)" v={row.structure ?? "—"} />
              <KV k="Momentum (RSI 14)" v={num(row.rsi, 1)} />
              <KV k="Volatility (ATR)" v={row.atr_pips != null ? `${row.atr_pips.toFixed(1)} pips · ${pct((row.atr_percentile ?? 0) * 100, 0, false)} pctile` : "—"} />
              <KV k="Asian range" v={lv?.asia_low ? `${price(lv.asia_low, 2)} – ${price(lv.asia_high, 2)}${lv.asia_complete ? "" : " (forming)"}` : "—"} />
              <KV k="Prior day H / L" v={lv?.prev_day_high ? `${price(lv.prev_day_high, 2)} / ${price(lv.prev_day_low, 2)}` : "—"} />
              {!row.data_ok && <p className="text-[11.5px] text-warn mt-2">{row.data_issues.join("; ")}</p>}
            </> : <Empty>Waiting for analysis…</Empty>}
          </Panel>
          <Panel title="USD & yields">
            <KV k="USD strength (24h, derived)" v={usd == null ? "—" : pct(usd, 2)} tone={tone(-(usd ?? 0))} />
            <KV k="Gold implication" v={usd == null ? "—" : usd < -0.05 ? "supportive (USD weak)" : usd > 0.05 ? "headwind (USD strong)" : "neutral"} />
            <KV k="US 10Y Treasury" v={y ? `${y.value.toFixed(2)}% · ${y.change_5d_bp > 0 ? "+" : ""}${y.change_5d_bp}bp 5d (${y.trend})` : "—"} />
            {y && <div className="mt-2"><LineChart points={y.history.map((h) => ({ t: Math.floor(new Date(h.date).getTime() / 1000), v: h.value }))} height={110} area={false}
              color={y.trend === "rising" ? "down" : "up"} /></div>}
            <p className="text-[10.5px] text-mute mt-1">{y?.source} as of {y?.date}. Rising real yields and a firm USD are typical headwinds for gold.</p>
          </Panel>
        </div>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-3 mt-3">
        <div className="space-y-3">
          <div className="label">Latest XAU/USD proposals</div>
          {(g.data?.decisions || []).slice(0, 3).map((d) => <ProposalCard key={d.id} p={d} />)}
          {g.data && !g.data.decisions.length && <Panel><Empty>No gold proposals yet. The gold session model looks for Asian-range sweeps and accepted breakouts during the London and New York opens.</Empty></Panel>}
        </div>
        <div className="flex flex-col gap-3">
          <Panel title="USD events (next 3 days)"><CalendarList events={g.data?.usd_events || []} compact /></Panel>
          {g.data && <Panel title="Contract specification">
            <KV k="Contract size" v={`${g.data.spec.contract_size} oz / lot`} /><KV k="Pip" v={`$${g.data.spec.pip_size}`} />
            <KV k="Pip value" v={`$${g.data.spec.pip_value_usd_per_lot} per lot`} /><KV k="Min lot" v={g.data.spec.min_lot} />
            <KV k="Margin" v={`${(g.data.spec.margin_rate * 100).toFixed(0)}% (${Math.round(1 / g.data.spec.margin_rate)}:1)`} />
            <p className="text-[10.5px] text-mute mt-2">Defaults — MT5 brokers can differ; verify your broker&apos;s specification.</p>
          </Panel>}
        </div>
      </div>
    </div>
  );
}
