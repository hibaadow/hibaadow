"use client";
import Link from "next/link";
import { post } from "@/lib/api";
import { duration, lots, price, signedUsd, tone, usd } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Position } from "@/lib/types";
import { Chip, Confirm, Empty, SideChip } from "../ui";
import { useMe } from "../Shell";

export default function PositionsTable({ rows, onChange, compact = false }: { rows: Position[]; onChange?: () => void; compact?: boolean }) {
  const { quotes } = useLive();
  const me = useMe();
  if (!rows.length) return <Empty>No open positions. ATLAS opens a position only when a proposal passes every risk check and automatic trading is on.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr>
          <th>Instrument</th><th>Side</th><th className="text-right">Lots</th><th className="text-right">Entry</th><th className="text-right">Price</th>
          <th className="text-right">Stop</th><th className="text-right">TP1 / TP2</th>{!compact && <th className="text-right">Risk</th>}
          <th className="text-right">Unrealised</th>{!compact && <th>Strategy</th>}{!compact && <th>Age</th>}<th />
        </tr></thead>
        <tbody>
          {rows.map((p) => {
            const q = quotes[p.symbol];
            const close = q ? (p.side === "buy" ? q.bid : q.ask) : p.last_price ?? p.entry_price;
            const sg = p.side === "buy" ? 1 : -1;
            const r = (p.entry_price - p.initial_stop) * sg;
            const rNow = r > 0 ? ((close - p.entry_price) * sg) / r : 0;
            const upnl = p.unrealized_pnl ?? null;
            return (
              <tr key={p.id}>
                <td><Link href={p.symbol === "XAUUSD" ? "/gold" : `/terminal?symbol=${p.symbol}`} className="font-semibold hover:text-accent">{p.display}</Link>
                  {p.mode !== "paper" && <span className="ml-1.5 text-[10px] text-mute uppercase">{p.mode}</span>}</td>
                <td><SideChip side={p.side} /> {p.tp1_hit && <Chip tone="up">TP1</Chip>}</td>
                <td className="num text-right">{lots(p.lots)}</td>
                <td className="num text-right">{price(p.entry_price, p.digits)}</td>
                <td className="num text-right">{price(close, p.digits)}</td>
                <td className="num text-right text-down">{price(p.stop_price, p.digits)}</td>
                <td className="num text-right text-up">{price(p.tp1, p.digits)}{p.tp2 ? ` / ${price(p.tp2, p.digits)}` : ""}</td>
                {!compact && <td className="num text-right">{usd(p.risk_amount)}</td>}
                <td className={`num text-right ${tone(upnl ?? rNow)}`}>{upnl == null ? "—" : signedUsd(upnl)} <span className="text-mute">({rNow >= 0 ? "+" : ""}{rNow.toFixed(2)}R)</span></td>
                {!compact && <td className="text-ink-2">{p.strategy}</td>}
                {!compact && <td className="num text-ink-2">{duration(p.duration_s)}</td>}
                <td className="text-right">
                  {me?.permissions.trade && (
                    <Confirm label="Close" confirmLabel="Close at market" className="btn !h-7"
                      onConfirm={async () => { await post(`/api/positions/${p.id}/close`); setTimeout(() => onChange?.(), 4000); }} />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
