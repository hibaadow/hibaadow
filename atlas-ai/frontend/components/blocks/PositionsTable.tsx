"use client";
import Link from "next/link";
import { post } from "@/lib/api";
import { duration, pair, price, qty, signedUsd, tone, usd } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Position } from "@/lib/types";
import { Chip, Confirm, Empty } from "../ui";
import { useMe } from "../Shell";

export default function PositionsTable({ rows, onChange, compact = false }: { rows: Position[]; onChange?: () => void; compact?: boolean }) {
  const { quotes } = useLive();
  const me = useMe();
  if (!rows.length) return <Empty>No open positions. The agent opens paper positions only when a signal passes every risk check and automatic paper trading is on.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr>
          <th>Asset</th><th>Status</th><th className="text-right">Qty</th><th className="text-right">Entry</th><th className="text-right">Mark</th>
          <th className="text-right">Stop</th><th className="text-right">TP1 / TP2</th>{!compact && <th className="text-right">Risk</th>}
          <th className="text-right">Unrealised</th>{!compact && <th>Strategy</th>}{!compact && <th>Age</th>}<th />
        </tr></thead>
        <tbody>
          {rows.map((p) => {
            const mark = quotes[p.symbol]?.bid ?? p.last_price ?? p.entry_price;
            const upnl = p.status === "open" ? p.qty * (mark - p.entry_price) : 0;
            const r = p.entry_price - p.initial_stop;
            const rNow = r > 0 ? (mark - p.entry_price) / r : 0;
            return (
              <tr key={p.id}>
                <td><Link href={`/terminal?symbol=${p.symbol}`} className="font-semibold hover:text-accent">{pair(p.symbol)}</Link></td>
                <td>{p.status === "pending" ? <Chip tone="warn">FILLING</Chip> : p.tp1_hit ? <Chip tone="up">TP1 HIT</Chip> : <Chip tone="accent">OPEN</Chip>}</td>
                <td className="num text-right">{qty(p.qty)}</td>
                <td className="num text-right">{price(p.entry_price)}</td>
                <td className="num text-right">{price(mark)}</td>
                <td className="num text-right text-down">{price(p.stop_price)}</td>
                <td className="num text-right text-up">{price(p.tp1)}{p.tp2 ? ` / ${price(p.tp2)}` : ""}</td>
                {!compact && <td className="num text-right">{usd(p.risk_amount)}</td>}
                <td className={`num text-right ${tone(upnl)}`}>{signedUsd(upnl)} <span className="text-mute">({rNow >= 0 ? "+" : ""}{rNow.toFixed(2)}R)</span></td>
                {!compact && <td className="text-ink-2">{p.strategy}</td>}
                {!compact && <td className="num text-ink-2">{duration(p.duration_s)}</td>}
                <td className="text-right">
                  {me?.permissions.trade && (
                    <Confirm label="Close" confirmLabel="Close at market" className="btn !h-7"
                      onConfirm={async () => { await post(`/api/positions/${p.id}/close`); setTimeout(() => onChange?.(), 3500); }} />
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
