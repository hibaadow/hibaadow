"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import ChartPanel, { type TF } from "@/components/blocks/ChartPanel";
import PositionPanel from "@/components/blocks/PositionPanel";
import PositionsTable from "@/components/blocks/PositionsTable";
import ProposalCard from "@/components/blocks/ProposalCard";
import { type Level } from "@/components/charts";
import { Empty, KV, Panel, PageHeader, SideChip, SignalChip } from "@/components/ui";
import { lots, num, pct, price, tone } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { Markets, Order, Position, Proposal } from "@/lib/types";

const FX = ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY"];

function Terminal() {
  const params = useSearchParams();
  const router = useRouter();
  const raw = (params.get("symbol") || "EURUSD").toUpperCase();
  const symbol = FX.includes(raw) ? raw : "EURUSD";
  const tf = (params.get("tf") || "5m") as TF;
  const set = (k: string, v: string) => { const p = new URLSearchParams(params.toString()); p.set(k, v); router.replace(`/terminal?${p}`); };
  const { quotes } = useLive();
  const mk = usePoll<Markets>("/api/markets", 15000, ["scanner"]);
  const positions = usePoll<Position[]>("/api/positions?status=open", 5000, ["positions"]);
  const orders = usePoll<Order[]>("/api/orders?status=open", 5000, ["positions"]);
  const props = usePoll<Proposal[]>(`/api/analyst/proposals?symbol=${symbol}&limit=3`, 20000, ["scanner"]);
  const row = mk.data?.forex.find((r) => r.symbol === symbol);
  const pos = positions.data?.find((p) => p.symbol === symbol);
  const q = quotes[symbol] ?? (row?.bid != null && row?.ask != null ? { bid: row.bid, ask: row.ask, ts: 0 } : undefined);
  const digits = row?.digits ?? (symbol.endsWith("JPY") ? 3 : 5);
  const pip = symbol.endsWith("JPY") ? 0.01 : 0.0001;
  const s = mk.data?.strength || {};
  const levels: Level[] = useMemo(() => {
    const out: Level[] = [];
    const lv = row?.levels;
    if (lv?.prev_day_high) out.push({ price: lv.prev_day_high, label: "PDH", color: "accent" }, { price: lv.prev_day_low!, label: "PDL", color: "accent" });
    if (pos) out.push({ price: pos.entry_price, label: "ENTRY", color: "accent" }, { price: pos.stop_price, label: "SL", color: "down" }, { price: pos.tp1, label: "TP1", color: "up" });
    return out;
  }, [row, pos]);
  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title={`${symbol.slice(0, 3)}/${symbol.slice(3)} · Forex Terminal`}
        subtitle={<>Bid <span className="num text-ink">{price(q?.bid, digits)}</span> · Ask <span className="num text-ink">{price(q?.ask, digits)}</span>
          {q && <> · spread <span className="num">{((q.ask - q.bid) / pip).toFixed(1)} pips</span></>} · {row?.session ?? "—"}
          {row?.change_24h_pct != null && <> · 24h <span className={`num ${tone(row.change_24h_pct)}`}>{pct(row.change_24h_pct)}</span></>}</>}
        right={<select className="input" value={symbol} onChange={(e) => set("symbol", e.target.value)}>{FX.map((x) => <option key={x} value={x}>{x.slice(0, 3)}/{x.slice(3)}</option>)}</select>} />
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-3">
        <ChartPanel symbol={symbol} tf={tf} onTf={(t) => set("tf", t)} levels={levels} />
        <div className="flex flex-col gap-3">
          {pos && <PositionPanel pos={pos} />}
          <Panel title="Pair analysis" right={row && <span className="flex gap-1">{row.direction && <SideChip side={row.direction} />}<SignalChip value={row.signal} /></span>}>
            {row ? <>
              <KV k="Trend 1h / 4h" v={`${row.trend_1h ?? "—"} / ${row.trend_4h ?? "—"}`} /><KV k="Structure" v={row.structure ?? "—"} />
              <KV k="RSI 14" v={num(row.rsi, 1)} /><KV k="ATR" v={row.atr_pips != null ? `${row.atr_pips.toFixed(1)} pips` : "—"} />
              <KV k={`${symbol.slice(0, 3)} strength`} v={pct(s[symbol.slice(0, 3)], 2)} tone={tone(s[symbol.slice(0, 3)])} />
              <KV k={`${symbol.slice(3)} strength`} v={pct(s[symbol.slice(3)], 2)} tone={tone(s[symbol.slice(3)])} />
              <KV k="Spread limit" v={`${row.spread_limit} pips`} />
              {!row.data_ok && <p className="text-[11.5px] text-warn mt-2">{row.data_issues.join("; ")}</p>}
            </> : <Empty>Waiting for analysis…</Empty>}
          </Panel>
          <Panel title="Pending orders" pad={false}>
            {(orders.data || []).filter((o) => o.symbol === symbol).length ? (
              <table className="tbl"><tbody>{orders.data!.filter((o) => o.symbol === symbol).map((o) => <tr key={o.id}><td className={o.purpose === "stop" ? "text-down" : "text-up"}>{o.side.toUpperCase()} {o.type} · {o.purpose}</td>
                <td className="num text-right">{lots(o.lots)}</td><td className="num text-right">{price(o.limit_price ?? o.stop_price, digits)}</td></tr>)}</tbody></table>) : <Empty>No working orders for this pair.</Empty>}
          </Panel>
        </div>
      </div>
      {(props.data || []).length > 0 && <div className="mt-3 space-y-3"><div className="label">Latest proposals</div>{props.data!.map((p) => <ProposalCard key={p.id} p={p} />)}</div>}
      <Panel title="All active positions" pad={false} className="mt-3"><PositionsTable rows={positions.data || []} onChange={positions.refresh} /></Panel>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="text-mute text-[12px]">Loading…</div>}><Terminal /></Suspense>;
}
