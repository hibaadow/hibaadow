"use client";
import { lots, num, price, time, usd } from "@/lib/format";
import type { Proposal } from "@/lib/types";
import { Chip, SideChip, SignalChip } from "../ui";

export default function ProposalCard({ p }: { p: Proposal }) {
  const breakdown = Object.entries(p.score_breakdown || {}).filter(([k]) => k !== "risk_checks") as [string, { points: number; max: number; why: string }][];
  const checks = (p.score_breakdown?.risk_checks || []) as { name: string; passed: boolean; detail: string }[];
  return (
    <div className="panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-semibold">{p.display}</span><SideChip side={p.direction} /><SignalChip value={p.classification} />
        <span className="num text-[12px] text-ink-2">confidence {p.confidence}/100</span>
        <span className="flex-1" />
        {p.executed ? <Chip tone="up">EXECUTED</Chip> : <Chip tone="mute">NOT EXECUTED</Chip>}
        <span className="num text-[11px] text-mute">{time(p.ts, true)} · {p.strategy_label} · {p.timeframe}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3 mt-3 text-[12px]">
        {[["Entry", price(p.entry, p.digits)], ["Stop-loss", price(p.stop_loss, p.digits)], ["Take-profit", price(p.take_profit, p.digits)], ["TP2", price(p.take_profit_2, p.digits)],
          ["Reward : risk", p.risk_reward ? `${num(p.risk_reward, 2)} : 1` : "—"], ["Position size", p.lots != null ? `${lots(p.lots)} lots` : "—"],
          ["Capital at risk", usd(p.risk_amount)], ["Est. costs", p.est_costs?.total_usd != null ? usd(p.est_costs.total_usd) : "—"]].map(([k, v]) => (
          <div key={k}><div className="label">{k}</div><div className="num mt-0.5">{v}</div></div>))}
      </div>
      {p.est_costs?.total_usd != null && <div className="text-[11px] text-mute mt-1 num">costs: spread {usd(p.est_costs.spread_usd)} ({num(p.est_costs.spread_pips, 1)} pips) · commission {usd(p.est_costs.commission_usd)} · slippage {usd(p.est_costs.slippage_usd)}</div>}
      <div className="grid md:grid-cols-3 gap-4 mt-4">
        <div><div className="label mb-1">Supporting evidence</div>
          <ul className="space-y-1">{(p.evidence || []).map((e, i) => <li key={i} className="text-[12px]"><Chip tone="accent">{e.category}</Chip> <span className="text-ink-2">{e.detail}</span></li>)}</ul></div>
        <div><div className="label mb-1">Invalidation</div>
          <ul className="space-y-1 list-disc pl-4">{(p.invalidation || []).map((x, i) => <li key={i} className="text-[12px] text-ink-2">{x}</li>)}</ul>
          <div className="label mt-3 mb-1">Relevant economic events</div>
          {(p.events || []).length ? (p.events || []).map((e, i) => <div key={i} className="text-[11.5px] text-ink-2 num">{new Date(e.time).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" })} {e.currency} <span className={e.impact === "High" ? "text-down" : "text-warn"}>{e.impact}</span> {e.title}</div>)
            : <div className="text-[11.5px] text-mute">None in the next 24h.</div>}</div>
        <div><div className="label mb-1">Confidence breakdown</div>
          {breakdown.map(([k, v]) => <div key={k} className="flex justify-between gap-2 text-[11.5px]" title={v.why}><span className="text-ink-2">{k.replace(/_/g, " ")}</span>
            <span className={`num ${v.points < 0 ? "text-down" : ""}`}>{num(v.points, 1)}{v.max ? ` / ${v.max}` : ""}</span></div>)}</div>
      </div>
      <p className="text-[12px] text-ink-2 mt-4 leading-snug">{p.explanation}</p>
      {p.ai_commentary && <p className="text-[12px] text-[#2dd4bf] mt-2 leading-snug">AI commentary: {p.ai_commentary}</p>}
      {!p.executed && p.rejected_reason && <p className="text-[12px] text-warn mt-2 leading-snug">Rejected: {p.rejected_reason}</p>}
      {checks.length > 0 && <details className="mt-2"><summary className="text-[11.5px] text-mute cursor-pointer">Risk checks ({checks.filter((c) => !c.passed).length} failed)</summary>
        <ul className="mt-1 grid md:grid-cols-2 gap-x-6">{checks.map((c, i) => <li key={i} className="text-[11.5px] flex gap-2"><span className={c.passed ? "text-up" : "text-down"}>{c.passed ? "✓" : "✗"}</span>
          <span className="text-ink-2 w-[150px] shrink-0">{c.name}</span><span className="text-mute">{c.detail}</span></li>)}</ul></details>}
    </div>
  );
}
