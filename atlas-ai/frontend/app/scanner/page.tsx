"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Chip, ErrorNote, Panel, PageHeader, RiskChip, SignalChip } from "@/components/ui";
import { compact, num, pair, pct, price, tone } from "@/lib/format";
import { useLive, usePoll } from "@/lib/live";
import type { ScannerRow } from "@/lib/types";

type Key = keyof ScannerRow;
const COLS: { key: Key; label: string; right?: boolean }[] = [
  { key: "symbol", label: "Asset" }, { key: "price", label: "Price", right: true }, { key: "change_24h_pct", label: "24h", right: true },
  { key: "volume_24h_usd", label: "Volume 24h", right: true }, { key: "market_cap", label: "Market cap", right: true },
  { key: "liquidity_usd", label: "Depth ±1%", right: true }, { key: "rsi", label: "RSI 5m", right: true }, { key: "trend", label: "Trend 1h" },
  { key: "volatility_pct", label: "ATR %", right: true }, { key: "signal", label: "Signal" }, { key: "confidence", label: "Confidence", right: true },
  { key: "risk_rating", label: "Risk" },
];

export default function Scanner() {
  const { data, error } = usePoll<{ rows: ScannerRow[]; ts: number | null; regime: string }>("/api/scanner", 10000, ["scanner"]);
  const { quotes } = useLive();
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "confidence", dir: -1 });
  const [q, setQ] = useState("");
  const [sig, setSig] = useState("all");
  const [risk, setRisk] = useState("all");
  const rows = useMemo(() => {
    let r = (data?.rows || []).map((x) => ({ ...x, price: quotes[x.symbol] ? (quotes[x.symbol].bid + quotes[x.symbol].ask) / 2 : x.price }));
    if (q) r = r.filter((x) => x.symbol.toLowerCase().includes(q.toLowerCase()));
    if (sig !== "all") r = r.filter((x) => (sig === "buy" ? x.signal.includes("BUY") : x.signal === sig));
    if (risk !== "all") r = r.filter((x) => x.risk_rating === risk);
    return [...r].sort((a, b) => {
      const av = a[sort.key] as unknown, bv = b[sort.key] as unknown;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv))) * sort.dir;
    });
  }, [data, quotes, q, sig, risk, sort]);

  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader title="Live Market Scanner"
        subtitle={<>Primary venue Binance spot (USDC pairs) · BTC 1h regime <b className="text-ink-2">{data?.regime ?? "—"}</b> · updated {data?.ts ? new Date(data.ts * 1000).toLocaleTimeString("en-GB") : "—"}</>}
        right={<>
          <input className="input w-[140px]" placeholder="Filter symbol" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" value={sig} onChange={(e) => setSig(e.target.value)}>
            <option value="all">All signals</option><option value="buy">Buy candidates</option><option value="WAIT">Wait</option>
            <option value="NO TRADE">No trade</option><option value="HIGH RISK">High risk</option>
          </select>
          <select className="input" value={risk} onChange={(e) => setRisk(e.target.value)}>
            <option value="all">All risk</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
        </>} />
      <ErrorNote error={error} />
      <Panel pad={false}>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr>{COLS.map((c) => (
              <th key={c.key} className={`cursor-pointer select-none ${c.right ? "text-right" : ""}`} onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (s.dir === 1 ? -1 : 1) : -1 }))}>
                {c.label}{sort.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
              </th>))}<th>Data</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol}>
                  <td><Link href={`/terminal?symbol=${r.symbol}`} className="font-semibold hover:text-accent">{pair(r.symbol)}</Link>
                    {r.strategy && <div className="text-[10.5px] text-mute">{r.strategy}</div>}</td>
                  <td className="num text-right">{price(r.price)}</td>
                  <td className={`num text-right ${tone(r.change_24h_pct)}`}>{pct(r.change_24h_pct)}</td>
                  <td className="num text-right">{compact(r.volume_24h_usd)}</td>
                  <td className="num text-right text-ink-2" title={r.market_cap ? "DexScreener, cross-checked against exchange price" : "not available from a verified source"}>{compact(r.market_cap)}</td>
                  <td className={`num text-right ${r.liquidity_usd != null && r.liquidity_usd < 250000 ? "text-warn" : ""}`}>{compact(r.liquidity_usd)}</td>
                  <td className={`num text-right ${r.rsi != null && (r.rsi > 70 ? "text-down" : r.rsi < 30 ? "text-up" : "")}`}>{num(r.rsi, 1)}</td>
                  <td><Chip tone={r.trend === "up" ? "up" : r.trend === "down" ? "down" : "mute"}>{r.trend.toUpperCase()}</Chip></td>
                  <td className="num text-right">{r.volatility_pct == null ? "—" : r.volatility_pct.toFixed(3) + "%"}</td>
                  <td><SignalChip value={r.signal} /></td>
                  <td className="text-right">
                    <div className="inline-flex items-center gap-2">
                      <div className="w-[52px] h-[5px] rounded-full bg-line overflow-hidden"><div className={`h-full ${r.confidence >= 60 ? "bg-up" : r.confidence >= 45 ? "bg-warn" : "bg-mute"}`} style={{ width: `${r.confidence}%` }} /></div>
                      <span className="num w-[22px]">{r.confidence || "—"}</span>
                    </div>
                  </td>
                  <td><RiskChip value={r.risk_rating} /></td>
                  <td title={r.data_issues.join("\n")}>{r.data_ok ? <span className="text-up text-[11px]">● fresh</span> : <span className="text-down text-[11px]">● {r.data_issues[0]?.slice(0, 28) || "issue"}</span>}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={13} className="text-center text-mute py-10">{data ? "No assets match the filters." : "Waiting for the first scan cycle…"}</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
      <p className="text-[11px] text-mute mt-3 leading-relaxed max-w-[900px]">
        Confidence is a 0–100 setup-quality score from deterministic rules — not a probability of profit. See calibration under Performance.
        Depth is order-book liquidity within ±1% of mid on the execution venue; assets below the configured minimum are rejected by the risk engine.
      </p>
    </div>
  );
}
