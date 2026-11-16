"use client";
import { useState } from "react";
import ProposalCard from "@/components/blocks/ProposalCard";
import { Empty, ErrorNote, PageHeader, Tabs } from "@/components/ui";
import { num, pct } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { Proposal } from "@/lib/types";

export default function Analyst() {
  const [cls, setCls] = useState<"all" | "gold" | "forex">("all");
  const [status, setStatus] = useState<"" | "executed" | "rejected">("");
  const { data, error } = usePoll<Proposal[]>(`/api/analyst/proposals?limit=60${cls !== "all" ? `&asset_class=${cls}` : ""}${status ? `&status=${status}` : ""}`, 20000, ["scanner"]);
  const cal = usePoll<{ buckets: { bucket: string; trades: number; win_rate: number | null; avg_r: number | null }[] }>("/api/analyst/calibration", 60000);
  return (
    <div className="max-w-[1400px] mx-auto">
      <PageHeader title="AI Trading Analyst" subtitle="Every proposal with instrument, direction, entry, stop, target, R:R, size, costs, evidence, events, invalidation and confidence — including the ones it rejects."
        right={<>
          <Tabs value={cls} onChange={setCls} options={[{ value: "all", label: "All" }, { value: "gold", label: "Gold" }, { value: "forex", label: "Forex" }]} />
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value as "")}><option value="">Executed + rejected</option><option value="executed">Executed</option><option value="rejected">Rejected</option></select>
        </>} />
      <div className="panel px-4 py-2.5 mb-3 text-[12px] text-ink-2 flex flex-wrap gap-x-6 gap-y-1">
        <span>Confidence is a deterministic setup-quality score — <b>not a probability of profit</b>. Measured calibration:</span>
        {(cal.data?.buckets || []).map((b) => <span key={b.bucket} className="num">{b.bucket}: {b.trades} trades{b.trades ? `, win ${pct(b.win_rate, 0, false)}, ${num(b.avg_r, 2)}R` : ""}</span>)}
      </div>
      <ErrorNote error={error} />
      <div className="space-y-3">{(data || []).map((p) => <ProposalCard key={p.id} p={p} />)}</div>
      {data && !data.length && <Empty>No proposals yet. Proposals appear once strategies find a setup with at least three independent confirmations.</Empty>}
    </div>
  );
}
