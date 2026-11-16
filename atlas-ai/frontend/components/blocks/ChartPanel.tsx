"use client";
import { CandleChart, type Level } from "@/components/charts";
import { ErrorNote, Panel, Tabs } from "@/components/ui";
import { useLive, usePoll } from "@/lib/live";

type CandleResp = { candles: { t: number; o: number; h: number; l: number; c: number; v: number }[]; indicators: Record<string, (number | null)[]>;
  source: string; digits: number; quality: { issues: string[] } };
export const TFS = ["1m", "5m", "15m", "1h", "4h"] as const;
export type TF = (typeof TFS)[number];

export default function ChartPanel({ symbol, tf, onTf, levels, height = 520 }: { symbol: string; tf: TF; onTf: (t: TF) => void; levels: Level[]; height?: number }) {
  const { quotes } = useLive();
  const candles = usePoll<CandleResp>(`/api/market/${symbol}/candles?tf=${tf}&limit=400`, 30000);
  const q = quotes[symbol];
  return (
    <Panel pad={false} title={<span className="flex items-center gap-3">Price · {tf}
      <span className="hidden md:flex gap-2 text-[10.5px] font-normal"><span className="text-[#f0a538]">EMA9</span><span className="text-[#4f8cff]">EMA21</span>
        <span className="text-[#a970ff]">EMA50</span><span className="text-[#e8e8e8]">EMA200</span><span className="text-[#2dd4bf]">VWAP</span><span className="text-[#c084fc]">RSI</span></span></span>}
      right={<><span className="hidden md:inline text-[10.5px] text-mute">source: {candles.data?.source ?? "—"}</span>
        <Tabs value={tf} onChange={onTf} options={TFS.map((t) => ({ value: t, label: t }))} /></>}>
      <ErrorNote error={candles.error} />
      {candles.data && candles.data.candles.length > 1
        ? <CandleChart candles={candles.data.candles} overlays={candles.data.indicators} levels={levels} live={q ? (q.bid + q.ask) / 2 : null} height={height} digits={candles.data.digits} />
        : <div style={{ height }} className="grid place-items-center text-mute text-[12px] px-6 text-center">{candles.data ? "Not enough bars yet. With the public quote feed, ATLAS builds 1-minute bars as it runs; connect OANDA or MT5 for full history." : "Loading market data…"}</div>}
      {!!candles.data?.quality.issues.length && <div className="px-4 py-2 text-[11px] text-warn border-t border-line">Data quality: {candles.data.quality.issues.join("; ")}</div>}
    </Panel>
  );
}
