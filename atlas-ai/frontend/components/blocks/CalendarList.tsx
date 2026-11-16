"use client";
import type { EconEvent } from "@/lib/types";
import { Chip, Empty } from "../ui";

export default function CalendarList({ events, max = 100, compact = false }: { events: EconEvent[]; max?: number; compact?: boolean }) {
  if (!events.length) return <Empty>No matching events.</Empty>;
  const now = Date.now();
  return (
    <ul className="divide-y divide-line/60">
      {events.slice(0, max).map((e, i) => {
        const t = new Date(e.time);
        const mins = (t.getTime() - now) / 60000;
        return (
          <li key={i} className={`py-2 flex items-center gap-3 ${mins < -60 ? "opacity-50" : ""}`}>
            <span className="num text-[11px] text-ink-2 w-[92px] shrink-0">{t.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })}</span>
            <span className="num text-[11.5px] font-semibold w-[34px] shrink-0">{e.currency}</span>
            {compact ? <span className={`w-[6px] h-[6px] rounded-full shrink-0 ${e.impact === "High" ? "bg-down" : e.impact === "Medium" ? "bg-warn" : "bg-mute"}`} title={e.impact} />
              : <Chip tone={e.impact === "High" ? "down" : e.impact === "Medium" ? "warn" : "mute"}>{e.impact.toUpperCase()}</Chip>}
            <span className="text-[12.5px] flex-1 min-w-0 truncate" title={e.title}>{e.title}</span>
            {e.central_bank && <Chip tone="accent">{compact ? "CB" : "CENTRAL BANK"}</Chip>}
            {mins >= 0 && mins <= 120 && <span className="text-[10.5px] text-warn num">in {Math.round(mins)}m</span>}
            {!compact && (e.forecast || e.previous) && <span className="hidden md:inline text-[11px] text-mute num w-[150px] text-right">f {e.forecast || "—"} · p {e.previous || "—"}</span>}
          </li>
        );
      })}
    </ul>
  );
}
