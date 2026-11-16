"use client";
import Link from "next/link";
import { Chip, RiskChip, SideChip, SignalChip } from "@/components/ui";
import { num, pct, price, tone } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { MarketRow } from "@/lib/types";

const trendTone = (t?: string) => (t === "up" || t === "bullish" ? "up" : t === "down" || t === "bearish" ? "down" : "mute") as "up";

export default function MarketTable({ rows, compact = false }: { rows: MarketRow[]; compact?: boolean }) {
  const { quotes } = useLive();
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr>
          <th>Instrument</th><th className="text-right">Bid</th><th className="text-right">Ask</th><th className="text-right">Spread</th>
          {!compact && <th className="text-right">24h</th>}<th>1h / 4h trend</th>{!compact && <th>Structure</th>}{!compact && <th className="text-right">RSI</th>}
          {!compact && <th className="text-right">ATR</th>}<th>Signal</th><th className="text-right">Conf.</th>{!compact && <th>Risk</th>}<th>Data</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const q = quotes[r.symbol];
            const bid = q?.bid ?? r.bid, ask = q?.ask ?? r.ask;
            const pipSize = r.symbol.endsWith("JPY") ? 0.01 : r.asset_class === "gold" ? 0.1 : 0.0001;
            const spread = bid != null && ask != null ? (ask - bid) / pipSize : r.spread_pips;
            return (
              <tr key={r.symbol}>
                <td><Link href={r.symbol === "XAUUSD" ? "/gold" : `/terminal?symbol=${r.symbol}`} className="font-semibold hover:text-accent">{r.display}</Link>
                  {r.strategy && <div className="text-[10.5px] text-mute">{r.strategy}</div>}</td>
                <td className="num text-right">{price(bid, r.digits)}</td>
                <td className="num text-right">{price(ask, r.digits)}</td>
                <td className={`num text-right ${spread != null && spread > r.spread_limit ? "text-down" : ""}`}>{spread == null ? "—" : spread.toFixed(1)}</td>
                {!compact && <td className={`num text-right ${tone(r.change_24h_pct)}`}>{pct(r.change_24h_pct)}</td>}
                <td className="whitespace-nowrap"><Chip tone={trendTone(r.trend_1h)}>{(r.trend_1h || "—").toUpperCase()}</Chip> <Chip tone={trendTone(r.trend_4h)}>{(r.trend_4h || "—").toUpperCase()}</Chip></td>
                {!compact && <td><Chip tone={trendTone(r.structure)}>{(r.structure || "—").toUpperCase()}</Chip></td>}
                {!compact && <td className="num text-right">{num(r.rsi, 1)}</td>}
                {!compact && <td className="num text-right">{r.atr_pips == null ? "—" : `${r.atr_pips.toFixed(1)}p`}</td>}
                <td className="whitespace-nowrap">{r.direction && <SideChip side={r.direction} />} <SignalChip value={r.signal} /></td>
                <td className="num text-right">{r.confidence || "—"}</td>
                {!compact && <td><RiskChip value={r.risk_rating} /></td>}
                <td title={r.data_issues.join("\n")}>{r.data_ok ? <span className="text-up text-[11px]">● ready</span>
                  : <span className="text-warn text-[11px]">● {(r.data_issues[0] || "issue").slice(0, compact ? 22 : 40)}</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
