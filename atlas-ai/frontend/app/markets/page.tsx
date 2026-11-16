"use client";
import MarketTable from "@/components/blocks/MarketTable";
import { Bars } from "@/components/charts";
import { ErrorNote, Panel, PageHeader } from "@/components/ui";
import { usePoll } from "@/lib/live";
import type { Markets } from "@/lib/types";

export default function MarketsPage() {
  const { data, error } = usePoll<Markets>("/api/markets", 10000, ["scanner"]);
  const strength = Object.entries(data?.strength || {}).sort((a, b) => b[1] - a[1]);
  return (
    <div className="max-w-[1700px] mx-auto">
      <PageHeader title="Markets" subtitle={<>ATLAS trades two markets only: <b className="text-ink">GOLD</b> and <b className="text-ink">FOREX</b> · data source {data?.source ?? "—"} · analysis {data?.ts ? new Date(data.ts * 1000).toLocaleTimeString("en-GB") : "—"}</>} />
      <ErrorNote error={error} />
      <Panel title="GOLD" pad={false}><MarketTable rows={data?.gold || []} /></Panel>
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-3 mt-3">
        <Panel title="FOREX" pad={false}><MarketTable rows={data?.forex || []} /></Panel>
        <Panel title="Currency strength (24h, derived)">
          {strength.length ? <>
            <Bars values={strength.map(([, v]) => v)} labels={strength.map(([k]) => k)} height={200} />
            <p className="text-[11px] text-mute mt-3 leading-snug">Average 24-hour % change of each currency against the others across ATLAS&apos;s tracked pairs. Derived from live data, not an external index.</p>
          </> : <div className="text-[12px] text-mute">Needs ≥ 25 hourly bars per pair.</div>}
        </Panel>
      </div>
      <p className="text-[11px] text-mute mt-3 max-w-[1000px]">Spread in pips (red = above the configured limit). Confidence is a setup-quality score, not a probability. Without a broker data connection, candles are built from sampled public quotes and strategies wait until enough history has accumulated.</p>
    </div>
  );
}
