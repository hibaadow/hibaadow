"use client";
import { useEffect, useState } from "react";
import ActivityList from "@/components/blocks/ActivityList";
import { ErrorNote, Panel, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { Activity } from "@/lib/types";

const KINDS = ["all", "signal", "decision", "risk", "execution", "stop_adjust", "analysis", "scan", "token_scan", "ai", "system"];

export default function ActivityPage() {
  const [rows, setRows] = useState<Activity[]>([]);
  const [kind, setKind] = useState("all");
  const [symbol, setSymbol] = useState("");
  const [paused, setPaused] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { subscribe, connected } = useLive();
  const qs = () => `/api/activity?limit=150${kind !== "all" ? `&kind=${kind}` : ""}${symbol ? `&symbol=${symbol.toUpperCase()}` : ""}`;
  useEffect(() => { api<Activity[]>(qs()).then(setRows).catch((e) => setErr(e.message)); }, [kind, symbol]); // eslint-disable-line
  useEffect(() => subscribe((e) => {
    if (e.type !== "activity" || paused) return;
    const a = e.data as Activity;
    if ((kind === "all" || a.kind === kind) && (!symbol || a.symbol === symbol.toUpperCase())) setRows((r) => [a, ...r].slice(0, 400));
  }), [subscribe, kind, symbol, paused]);
  const more = async () => { const last = rows[rows.length - 1]; if (!last) return; const older = await api<Activity[]>(`${qs()}&before_id=${last.id}`); setRows((r) => [...r, ...older]); };
  return (
    <div className="max-w-[1200px] mx-auto">
      <PageHeader title="AI Activity Feed" subtitle={<>Every scan, decision, rejection, order and stop adjustment — with its explanation. {connected ? <span className="text-up">● streaming</span> : <span className="text-down">● reconnecting</span>}</>}
        right={<>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{k === "all" ? "All events" : k.replace("_", " ")}</option>)}</select>
          <input className="input w-[120px]" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <button className="btn" onClick={() => setPaused((p) => !p)}>{paused ? "▶ Resume" : "❚❚ Pause"}</button>
        </>} />
      <ErrorNote error={err} />
      <Panel><ActivityList rows={rows} />{rows.length >= 100 && <div className="text-center pt-3"><button className="btn" onClick={more}>Load older</button></div>}</Panel>
    </div>
  );
}
