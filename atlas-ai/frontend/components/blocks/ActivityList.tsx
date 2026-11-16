"use client";
import { time } from "@/lib/format";
import type { Activity } from "@/lib/types";
import { Empty } from "../ui";

const KIND: Record<string, { label: string; cls: string }> = {
  scan: { label: "SCAN", cls: "text-mute border-line-2" },
  analysis: { label: "ANALYSIS", cls: "text-ink-2 border-line-2" },
  signal: { label: "SIGNAL", cls: "text-accent border-accent/30" },
  decision: { label: "DECISION", cls: "text-warn border-warn/30" },
  risk: { label: "RISK", cls: "text-down border-down/30" },
  execution: { label: "EXECUTION", cls: "text-up border-up/30" },
  stop_adjust: { label: "STOP", cls: "text-warn border-warn/30" },
  monitor: { label: "MONITOR", cls: "text-ink-2 border-line-2" },
  token_scan: { label: "SOLANA", cls: "text-[#a970ff] border-[#a970ff]/30" },
  ai: { label: "AI", cls: "text-[#2dd4bf] border-[#2dd4bf]/30" },
  system: { label: "SYSTEM", cls: "text-ink-2 border-line-2" },
};

export default function ActivityList({ rows, dense = false }: { rows: Activity[]; dense?: boolean }) {
  if (!rows.length) return <Empty>Waiting for the agent… events appear here in real time.</Empty>;
  return (
    <ul className="divide-y divide-line/60">
      {rows.map((e) => {
        const k = KIND[e.kind] || KIND.system;
        return (
          <li key={e.id} className={`${dense ? "py-2" : "py-2.5"} flex gap-3`}>
            <span className="num text-[11px] text-mute w-[58px] shrink-0 pt-[1px]">{time(e.ts)}</span>
            <span className={`chip shrink-0 h-[18px] !px-1.5 !text-[9.5px] border ${k.cls}`}>{k.label}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] text-ink leading-snug break-words">{e.message}</div>
              {e.explanation && <div className={`text-[11.5px] text-mute leading-snug mt-0.5 break-words ${dense ? "line-clamp-2" : ""}`}>{e.explanation}</div>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
