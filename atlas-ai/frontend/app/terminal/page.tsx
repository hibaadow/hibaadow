"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import PositionsTable from "@/components/blocks/PositionsTable";
import { CandleChart, type Level } from "@/components/charts";
import { Chip, Empty, ErrorNote, KV, Panel, PageHeader, SignalChip, Tabs } from "@/components/ui";
import { compact, num, pair, pct, price, qty, signedUsd, time, tone, usd } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { Decision, Order, Position, ScannerRow } from "@/lib/types";

type CandleResp = { candles: { t: number; o: number; h: number; l: number; c: number; v: number }[]; indicators: Record<string, (number | null)[]>; source: string; quality: { issues: string[] } };
type Sig = { id: number; ts: string; symbol: string; strategy: string; entry: number; stop: number; targets: number[]; strength: number; reasons: string[] };
const TFS = ["1m", "5m", "15m", "1h", "4h"] as const;

function Terminal() {
  const params = useSearchParams();
  const router = useRouter();
  const symbol = (params.get("symbol") || "SOLUSDC").toUpperCase();
  const tf = (params.get("tf") || "5m") as (typeof TFS)[number];
  const set = (k: string, v: string) => { const p = new URLSearchParams(params.toString()); p.set(k, v); router.replace(`/terminal?${p}`); };
  const { quotes } = useLive();
  const candles = usePoll<CandleResp>(`/api/market/${symbol}/candles?tf=${tf}&limit=400`, 30000);
  const scanner = usePoll<{ rows: ScannerRow[] }>("/api/scanner", 15000, ["scanner"]);
  const positions = usePoll<Position[]>("/api/positions?status=open", 5000, ["positions"]);
  const orders = usePoll<Order[]>("/api/orders?status=open", 5000, ["positions"]);
  const signals = usePoll<Sig[]>(`/api/signals?symbol=${symbol}&limit=5`, 20000, ["scanner"]);
  const decisions = usePoll<Decision[]>(`/api/decisions?symbol=${symbol}&limit=5`, 20000, ["scanner"]);
  const row = scanner.data?.rows.find((r) => r.symbol === symbol);
  const pos = positions.data?.find((p) => p.symbol === symbol);
  const sig = signals.data?.[0];
  const dec = decisions.data?.[0];
  const q = quotes[symbol];
  const live = q ? q.bid : null;

  const levels: Level[] = useMemo(() => {
    if (pos) return [
      { price: pos.entry_price, label: "ENTRY", color: "accent" }, { price: pos.stop_price, label: "STOP", color: "down" },
      { price: pos.tp1, label: "TP1", color: "up" }, ...(pos.tp2 ? [{ price: pos.tp2, label: "TP2", color: "up" as const }] : [])];
    if (sig) return [{ price: sig.entry, label: "SIGNAL", color: "warn" }, { price: sig.stop, label: "STOP", color: "down" },
      ...sig.targets.map((t, i) => ({ price: t, label: `T${i + 1}`, color: "up" as const }))];
    return [];
  }, [pos, sig]);

  const symbols = scanner.data?.rows.map((r) => r.symbol) || [symbol];
  const rr = pos ? pos.rr : sig ? (sig.targets[0] - sig.entry) / (sig.entry - sig.stop) : null;

  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title={`${pair(symbol)} · Trading Terminal`}
        subtitle={<>Bid <span className="num text-ink">{price(q?.bid)}</span> · Ask <span className="num text-ink">{price(q?.ask)}</span>
          {q && <> · spread <span className="num">{(((q.ask - q.bid) / ((q.ask + q.bid) / 2)) * 1e4).toFixed(1)} bps</span></>}
          {row && <> · 24h <span className={`num ${tone(row.change_24h_pct)}`}>{pct(row.change_24h_pct)}</span> · vol {compact(row.volume_24h_usd)}</>}</>}
        right={<>
          <select className="input" value={symbol} onChange={(e) => set("symbol", e.target.value)}>
            {Array.from(new Set([symbol, ...symbols])).map((s) => <option key={s} value={s}>{pair(s)}</option>)}
          </select>
          <Tabs value={tf} onChange={(v) => set("tf", v)} options={TFS.map((t) => ({ value: t, label: t }))} />
        </>} />
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-3">
        <Panel pad={false} title={<span className="flex items-center gap-3">Price · {tf}
          <span className="flex gap-2 text-[10.5px] font-normal">
            <span className="text-[#f0a538]">EMA9</span><span className="text-[#4f8cff]">EMA21</span><span className="text-[#a970ff]">EMA50</span>
            <span className="text-[#e8e8e8]">EMA200</span><span className="text-[#2dd4bf]">VWAP</span><span className="text-[#c084fc]">RSI</span></span></span>}
          right={<span className="text-[10.5px] text-mute">source: {candles.data?.source ?? "—"} · closed + live bar</span>}>
          <ErrorNote error={candles.error} />
          {candles.data ? <CandleChart candles={candles.data.candles} overlays={candles.data.indicators} levels={levels} live={live} height={520} />
            : <div className="h-[520px] grid place-items-center text-mute text-[12px]">Loading market data…</div>}
          {!!candles.data?.quality.issues.length && <div className="px-4 py-2 text-[11px] text-warn border-t border-line">Data quality: {candles.data.quality.issues.join("; ")}</div>}
        </Panel>
        <div className="flex flex-col gap-3">
          <Panel title={pos ? "Position" : "Latest setup"} right={pos ? <Chip tone="accent">{pos.status.toUpperCase()}</Chip> : dec ? <SignalChip value={dec.classification} /> : null}>
            {pos ? (
              <>
                <KV k="Strategy" v={pos.strategy} />
                <KV k="Position size" v={`${qty(pos.qty)} (${usd(pos.position_value)})`} />
                <KV k="Entry (avg fill)" v={price(pos.entry_price)} />
                <KV k="Stop-loss" v={price(pos.stop_price)} tone="text-down" />
                <KV k="Take-profit 1 / 2" v={`${price(pos.tp1)} / ${price(pos.tp2)}`} tone="text-up" />
                <KV k="Risk / reward" v={rr ? `1 : ${num(rr, 2)}` : "—"} />
                <KV k="Capital at risk" v={usd(pos.risk_amount)} />
                <KV k="Unrealised" v={signedUsd(pos.qty * ((live ?? pos.entry_price) - pos.entry_price))} tone={tone((live ?? 0) - pos.entry_price)} />
                <KV k="Fees / slippage" v={`${usd(pos.fees)} / ${usd(pos.slippage)}`} />
                <p className="text-[11.5px] text-mute mt-3 leading-snug">{pos.entry_reason}</p>
                {pos.stop_history.length > 1 && (
                  <div className="mt-3"><div className="label mb-1">Stop adjustments</div>
                    {pos.stop_history.map((h, i) => <div key={i} className="text-[11px] text-ink-2 num">{time(h.ts)} → {price(h.stop)} <span className="text-mute font-sans">{h.reason}</span></div>)}</div>)}
              </>
            ) : sig ? (
              <>
                <KV k="Strategy" v={sig.strategy} />
                <KV k="Signal time" v={time(sig.ts, true)} />
                <KV k="Entry" v={price(sig.entry)} />
                <KV k="Stop-loss" v={price(sig.stop)} tone="text-down" />
                <KV k="Targets" v={sig.targets.map(price).join(" / ")} tone="text-up" />
                <KV k="Risk / reward (gross)" v={rr ? `1 : ${num(rr, 2)}` : "—"} />
                {dec && <KV k="Confidence" v={`${dec.confidence} / 100`} />}
                {dec && <p className="text-[11.5px] text-mute mt-3 leading-snug">{dec.executed ? "Executed." : `Not executed — ${dec.rejected_reason ?? "pending"}`}</p>}
                {dec?.ai_commentary && <p className="text-[11.5px] text-[#2dd4bf] mt-2 leading-snug">AI: {dec.ai_commentary}</p>}
              </>
            ) : <Empty>No signal yet for {pair(symbol)}. The agent evaluates every closed {tf === "1m" ? "5m" : "5m"} bar.</Empty>}
          </Panel>
          <Panel title="Open orders" pad={false}>
            {(orders.data || []).length ? (
              <table className="tbl"><thead><tr><th>Asset</th><th>Type</th><th className="text-right">Qty</th><th className="text-right">Price</th></tr></thead>
                <tbody>{orders.data!.map((o) => (
                  <tr key={o.id}><td>{pair(o.symbol)}</td><td><span className={o.purpose === "stop" ? "text-down" : o.purpose.startsWith("tp") ? "text-up" : ""}>{o.side.toUpperCase()} {o.type} · {o.purpose}</span></td>
                    <td className="num text-right">{qty(o.qty - o.filled_qty)}</td><td className="num text-right">{price(o.limit_price ?? o.stop_price)}</td></tr>))}</tbody></table>
            ) : <Empty>No working orders.</Empty>}
          </Panel>
        </div>
      </div>
      <Panel title="Active positions" pad={false} className="mt-3"><PositionsTable rows={positions.data || []} onChange={positions.refresh} /></Panel>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="text-mute text-[12px]">Loading…</div>}><Terminal /></Suspense>;
}
