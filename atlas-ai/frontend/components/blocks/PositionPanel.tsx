"use client";
import { KV, Panel, SideChip } from "@/components/ui";
import { lots, num, price, signedUsd, time, tone, usd } from "@/lib/format";
import type { Position } from "@/lib/types";

export default function PositionPanel({ pos }: { pos: Position }) {
  return (
    <Panel title={<span className="flex items-center gap-2">Open position <SideChip side={pos.side} /></span>}>
      <KV k="Strategy" v={pos.strategy} />
      <KV k="Size" v={`${lots(pos.lots)} lots (${pos.mode})`} />
      <KV k="Entry (avg fill)" v={price(pos.entry_price, pos.digits)} />
      <KV k="Stop-loss" v={price(pos.stop_price, pos.digits)} tone="text-down" />
      <KV k="Take-profit 1 / 2" v={`${price(pos.tp1, pos.digits)} / ${price(pos.tp2, pos.digits)}`} tone="text-up" />
      <KV k="Reward : risk" v={pos.rr ? `${num(pos.rr, 2)} : 1` : "—"} />
      <KV k="Stop distance" v={pos.stop_pips != null ? `${pos.stop_pips} pips × $${num(pos.pip_value_usd, 2)}/pip/lot` : "—"} />
      <KV k="Capital at risk" v={usd(pos.risk_amount)} />
      <KV k="Unrealised" v={pos.unrealized_pnl == null ? "—" : signedUsd(pos.unrealized_pnl)} tone={tone(pos.unrealized_pnl)} />
      <KV k="Commission" v={usd(pos.commission)} />
      {pos.broker_id && <KV k="Broker trade id" v={pos.broker_id} />}
      <p className="text-[11.5px] text-mute mt-3 leading-snug">{pos.entry_reason}</p>
      {pos.stop_history.length > 1 && <div className="mt-3"><div className="label mb-1">Stop adjustments</div>
        {pos.stop_history.map((h, i) => <div key={i} className="text-[11px] text-ink-2 num">{time(h.ts)} → {price(h.stop, pos.digits)} <span className="text-mute font-sans">{h.reason}</span></div>)}</div>}
    </Panel>
  );
}
