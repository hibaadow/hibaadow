"use client";
import { useState } from "react";
import CalendarList from "@/components/blocks/CalendarList";
import { useMe } from "@/components/Shell";
import { ErrorNote, Panel, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { usePoll } from "@/lib/live";
import type { EconEvent } from "@/lib/types";

export default function CalendarPage() {
  const me = useMe();
  const [impact, setImpact] = useState("Medium");
  const [cur, setCur] = useState("");
  const { data, error, refresh } = usePoll<{ events: EconEvent[]; source: string; fetched: number | null; blackout: Record<string, number | boolean> }>(
    `/api/calendar?impact=${impact}${cur ? `&currency=${cur}` : ""}`, 120000);
  const cb = (data?.events || []).filter((e) => e.central_bank);
  return (
    <div className="max-w-[1300px] mx-auto">
      <PageHeader title="Economic Calendar" subtitle={`${data?.source ?? ""} · updated ${data?.fetched ? new Date(data.fetched * 1000).toLocaleTimeString("en-GB") : "—"} · times shown in your local time`}
        right={<>
          <select className="input" value={impact} onChange={(e) => setImpact(e.target.value)}><option>High</option><option>Medium</option><option>Low</option></select>
          <select className="input" value={cur} onChange={(e) => setCur(e.target.value)}><option value="">All currencies</option>{["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"].map((c) => <option key={c}>{c}</option>)}</select>
          {me?.permissions.trade && <button className="btn" onClick={async () => { await post("/api/calendar/refresh"); setTimeout(refresh, 5000); }}>Refresh</button>}
        </>} />
      <ErrorNote error={error} />
      {data?.blackout && <div className="text-[12px] text-ink-2 panel px-4 py-2.5 mb-3">News blackout: no new trades from <b>{String(data.blackout.minutes_before)} min before</b> to <b>{String(data.blackout.minutes_after)} min after</b> any high-impact event in an instrument&apos;s currencies (gold: USD), widened by <b>{String(data.blackout.central_bank_extra_minutes)} min</b> for central-bank decisions. {data.blackout.enabled ? "" : <span className="text-down">Currently disabled.</span>}</div>}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-3">
        <Panel title="This week"><CalendarList events={data?.events || []} /></Panel>
        <Panel title="Central-bank events"><CalendarList events={cb} compact /></Panel>
      </div>
    </div>
  );
}
