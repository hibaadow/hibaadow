"use client";
import { useState } from "react";
import { Chip, ErrorNote, KV, Panel, PageHeader, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { duration, pair, price, qty, signedUsd, time, tone, usd } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { Position } from "@/lib/types";

type Detail = Position & { orders: { id: number; purpose: string; side: string; type: string; status: string; qty: number; filled_qty: number; avg_fill_price: number | null; fees: number }[];
  executions: { ts: string; qty: number; price: number; reference_price: number; fee: number; slippage_bps: number; liquidity: string }[];
  decision: { confidence: number; classification: string; explanation: string; ai_commentary: string | null } | null };

export default function History() {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const [q, setQ] = useState("");
  const [strategy, setStrategy] = useState("");
  const [page, setPage] = useState(1);
  const qs = `mode=${mode}&page=${page}&page_size=50${q ? `&q=${encodeURIComponent(q)}` : ""}${strategy ? `&strategy=${strategy}` : ""}`;
  const { data, error } = usePoll<{ total: number; rows: Position[] }>(`/api/trades?${qs}`, 30000, ["positions"]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const pages = Math.max(1, Math.ceil((data?.total || 0) / 50));
  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title="Trade Journal" subtitle={`${data?.total ?? 0} closed ${mode} trades · net P&L after fees and slippage`}
        right={<>
          <Tabs value={mode} onChange={(v) => { setMode(v); setPage(1); }} options={[{ value: "paper", label: "Paper" }, { value: "live", label: "Live" }]} />
          <input className="input w-[200px]" placeholder="Search asset, strategy, reason…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <select className="input" value={strategy} onChange={(e) => { setStrategy(e.target.value); setPage(1); }}>
            <option value="">All strategies</option>{["trend_following", "momentum", "breakout", "vwap_reversion"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <a className="btn" href={`/api/trades/export.csv?mode=${mode}${q ? `&q=${encodeURIComponent(q)}` : ""}${strategy ? `&strategy=${strategy}` : ""}`}>⇩ Export CSV</a>
        </>} />
      <ErrorNote error={error} />
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-3">
        <Panel pad={false}>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Closed</th><th>Asset</th><th>Strategy</th><th className="text-right">Size</th><th className="text-right">Entry</th><th className="text-right">Exit</th>
                <th className="text-right">Fees</th><th className="text-right">Slippage</th><th className="text-right">Gross</th><th className="text-right">Net</th><th className="text-right">R</th><th>Duration</th><th>Exit reason</th></tr></thead>
              <tbody>
                {(data?.rows || []).map((t) => (
                  <tr key={t.id} className="cursor-pointer" onClick={() => api<Detail>(`/api/positions/${t.id}`).then(setDetail)}>
                    <td className="num text-ink-2">{time(t.closed_at, true)}</td><td className="font-semibold">{pair(t.symbol)}</td><td className="text-ink-2">{t.strategy}</td>
                    <td className="num text-right">{qty(t.initial_qty)}</td><td className="num text-right">{price(t.entry_price)}</td><td className="num text-right">{price(t.exit_price)}</td>
                    <td className="num text-right text-ink-2">{usd(t.fees)}</td><td className="num text-right text-ink-2">{usd(t.slippage)}</td>
                    <td className={`num text-right ${tone(t.gross_pnl)}`}>{signedUsd(t.gross_pnl)}</td><td className={`num text-right font-semibold ${tone(t.net_pnl)}`}>{signedUsd(t.net_pnl)}</td>
                    <td className={`num text-right ${tone(t.r_multiple)}`}>{t.r_multiple == null ? "—" : `${t.r_multiple > 0 ? "+" : ""}${t.r_multiple.toFixed(2)}R`}</td>
                    <td className="num text-ink-2">{duration(t.duration_s)}</td><td className="text-ink-2 max-w-[260px] truncate" title={t.exit_reason || ""}>{t.exit_reason}</td>
                  </tr>))}
                {!data?.rows.length && <tr><td colSpan={13} className="text-center text-mute py-10">No closed {mode} trades yet{mode === "live" ? " — live trading is disabled by default" : ""}.</td></tr>}
              </tbody>
            </table>
          </div>
          {pages > 1 && <div className="flex justify-end items-center gap-2 p-3 border-t border-line text-[12px]">
            <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button><span className="num text-mute">{page} / {pages}</span>
            <button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button></div>}
        </Panel>
        <Panel title={detail ? `Trade #${detail.id} · ${pair(detail.symbol)}` : "Trade detail"} right={detail && <Chip tone={detail.net_pnl >= 0 ? "up" : "down"}>{detail.net_pnl >= 0 ? "WIN" : "LOSS"}</Chip>}>
          {!detail ? <div className="text-[12px] text-mute">Select a trade to see entries, exits, fills, fees and the decision that opened it.</div> : (
            <div className="text-[12.5px]">
              <KV k="Opened" v={time(detail.opened_at, true)} /><KV k="Closed" v={time(detail.closed_at, true)} />
              <KV k="Initial stop" v={price(detail.initial_stop)} /><KV k="Targets" v={`${price(detail.tp1)} / ${price(detail.tp2)}`} />
              <KV k="Capital at risk" v={usd(detail.risk_amount)} /><KV k="Net P&L" v={signedUsd(detail.net_pnl)} tone={tone(detail.net_pnl)} />
              <div className="label mt-4 mb-1">Entry reason</div><p className="text-ink-2 leading-snug">{detail.entry_reason}</p>
              <div className="label mt-3 mb-1">Exit reason</div><p className="text-ink-2 leading-snug">{detail.exit_reason}</p>
              {detail.decision && <><div className="label mt-3 mb-1">Decision ({detail.decision.classification}, {detail.decision.confidence}/100)</div><p className="text-mute leading-snug">{detail.decision.explanation}</p>
                {detail.decision.ai_commentary && <p className="text-[#2dd4bf] mt-2 leading-snug">AI: {detail.decision.ai_commentary}</p>}</>}
              <div className="label mt-4 mb-1">Fills</div>
              {detail.executions.map((e, i) => <div key={i} className="num text-[11.5px] text-ink-2 py-0.5">{time(e.ts)} {qty(e.qty)} @ {price(e.price)} <span className="text-mute">ref {price(e.reference_price)} · {e.slippage_bps.toFixed(1)}bps · fee {usd(e.fee, 4)} · {e.liquidity}</span></div>)}
            </div>)}
        </Panel>
      </div>
    </div>
  );
}
