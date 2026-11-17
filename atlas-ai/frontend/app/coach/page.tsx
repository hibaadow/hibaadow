"use client";
import { useEffect, useRef, useState } from "react";
import { useMe } from "@/components/Shell";
import { Chip, Empty, ErrorNote, KV, Panel, PageHeader, SideChip } from "@/components/ui";
import { api } from "@/lib/api";
import { lots, num, price, time, usd } from "@/lib/format";
import { usePoll } from "@/lib/live";

type Check = { name: string; passed: boolean; detail: string };
type Reading = { readable: boolean; instrument: string; timeframe: string; platform: string; visible_price: number | null; trend: string; observations: string[];
  key_levels: { price: number; kind: string; note: string }[]; recommendation: string; entry: number | null; stop_loss: number | null; take_profit: number | null;
  rationale: string; invalidation: string[]; risks: string[]; uncertainties: string[]; confidence: number };
type Result = { reading: Reading; checks: Check[]; final: string; final_reasons: string[]; disclaimer: string;
  sizing: { lots: number; risk_usd: number; stop_pips: number; pip_value_usd: number; target: number; net_rr: number; margin_usd: number; costs: { total_usd?: number }; notes: string[]; balance: number; risk_pct: number } | null;
  live: { bid: number; ask: number; spread_pips: number; screenshot_price: number | null; difference_pips: number | null } | null;
  atlas_view: Record<string, any> | null; events: { title: string; currency: string; time: string; impact: string }[] };
type Row = { id: number; ts: string; instrument: string | null; ai_recommendation: string | null; final: string; note: string | null; result: Result };

const DIGITS: Record<string, number> = { XAUUSD: 2, USDJPY: 3, GBPJPY: 3, EURJPY: 3 };
const finalStyle = (f: string) => (f === "BUY" ? "bg-up/15 text-up border-up/40" : f === "SELL" ? "bg-down/15 text-down border-down/40" : f === "WAIT" ? "bg-warn/12 text-warn border-warn/35" : "bg-white/[0.04] text-ink-2 border-line-2");

function ResultCard({ r, ts }: { r: Result; ts?: string }) {
  const rd = r.reading;
  const d = DIGITS[rd.instrument] ?? 5;
  const disp = rd.instrument?.length === 6 ? `${rd.instrument.slice(0, 3)}/${rd.instrument.slice(3)}` : rd.instrument;
  return (
    <div className="panel p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`chip border !text-[15px] !px-3 !py-1 ${finalStyle(r.final)}`}>{r.final === "BUY" || r.final === "SELL" ? `${r.final} ${disp}` : r.final}</span>
        <span className="text-[13px] text-ink-2">{disp} · {rd.timeframe} · {rd.platform}</span>
        {rd.recommendation !== r.final && <span className="text-[11.5px] text-warn">AI suggested {rd.recommendation} — ATLAS checks changed it</span>}
        <span className="flex-1" />{ts && <span className="text-[11px] text-mute num">{time(ts, true)}</span>}
      </div>
      <ul className="text-[12.5px] text-ink-2 list-disc pl-5 space-y-0.5">{r.final_reasons.filter(Boolean).map((x, i) => <li key={i}>{x}</li>)}</ul>
      {(rd.recommendation === "BUY" || rd.recommendation === "SELL") && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12.5px]">
          {[["Entry", price(rd.entry, d)], ["Stop-loss", price(rd.stop_loss, d)], ["Take-profit (ATLAS)", price(r.sizing?.target ?? rd.take_profit, d)],
            ["Lot size", r.sizing ? `${lots(r.sizing.lots)} lots` : "—"], ["Risk", r.sizing ? `${usd(r.sizing.risk_usd)} (${r.sizing.risk_pct}%)` : "—"],
            ["Reward : risk (net)", r.sizing ? `${num(r.sizing.net_rr, 2)} : 1` : "—"], ["Stop distance", r.sizing ? `${r.sizing.stop_pips} pips` : "—"],
            ["Est. costs", r.sizing?.costs?.total_usd != null ? usd(r.sizing.costs.total_usd) : "—"]].map(([k, v]) => (
            <div key={k} className="panel px-3 py-2"><div className="label">{k}</div><div className="num mt-0.5 text-[14px]">{v}</div></div>))}
        </div>)}
      {r.sizing?.notes?.length ? <p className="text-[11.5px] text-mute">{r.sizing.notes.join(" · ")}</p> : null}
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <div className="label mb-1">What the AI sees on your chart</div>
          <p className="text-[12.5px] text-ink-2 mb-1.5">{rd.rationale}</p>
          <ul className="text-[12px] text-ink-2 list-disc pl-4">{rd.observations.map((o, i) => <li key={i}>{o}</li>)}</ul>
          {rd.key_levels.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{rd.key_levels.map((l, i) => <Chip key={i} tone={l.kind === "support" || l.kind === "demand" ? "up" : l.kind === "resistance" || l.kind === "supply" ? "down" : "mute"}>{l.kind} {price(l.price, d)}</Chip>)}</div>}
          <div className="label mt-3 mb-1">Trade is invalid if</div>
          <ul className="text-[12px] text-ink-2 list-disc pl-4">{rd.invalidation.map((o, i) => <li key={i}>{o}</li>)}</ul>
          {rd.uncertainties.length > 0 && <><div className="label mt-3 mb-1">Could not read clearly</div><ul className="text-[12px] text-warn list-disc pl-4">{rd.uncertainties.map((o, i) => <li key={i}>{o}</li>)}</ul></>}
          <div className="text-[11px] text-mute mt-2">AI chart-reading confidence {rd.confidence}/100 — a quality score, not a probability of profit.</div>
        </div>
        <div>
          <div className="label mb-1">ATLAS checks (live data & your risk rules)</div>
          <ul className="space-y-1">{r.checks.map((c, i) => <li key={i} className="text-[12px] flex gap-2"><span className={c.passed ? "text-up" : "text-down"}>{c.passed ? "✓" : "✗"}</span>
            <span className="text-ink-2 w-[130px] shrink-0">{c.name.replace(/_/g, " ")}</span><span className="text-mute">{c.detail}</span></li>)}</ul>
          {r.live && <div className="mt-3"><KV k="Live bid / ask" v={`${price(r.live.bid, d)} / ${price(r.live.ask, d)}`} /><KV k="Live spread" v={`${r.live.spread_pips} pips`} />
            <KV k="Screenshot vs live" v={r.live.difference_pips == null ? "price not readable" : `${r.live.difference_pips} pips apart`} /></div>}
          {r.atlas_view && <div className="mt-2"><KV k="ATLAS own view" v={<span className="flex items-center gap-1">{r.atlas_view.direction && <SideChip side={r.atlas_view.direction} />}{r.atlas_view.signal ?? "—"}</span>} />
            <KV k="1h / 4h trend" v={`${r.atlas_view.trend_1h ?? "—"} / ${r.atlas_view.trend_4h ?? "—"}`} /></div>}
          {r.events.length > 0 && <><div className="label mt-3 mb-1">High-impact events (next 12h)</div>
            {r.events.map((e, i) => <div key={i} className="text-[11.5px] text-ink-2 num">{new Date(e.time).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" })} {e.currency} <span className="text-down">{e.impact}</span> {e.title}</div>)}</>}
          {rd.risks.length > 0 && <><div className="label mt-3 mb-1">Risks</div><ul className="text-[12px] text-ink-2 list-disc pl-4">{rd.risks.map((o, i) => <li key={i}>{o}</li>)}</ul></>}
        </div>
      </div>
      <p className="text-[11px] text-mute border-t border-line pt-3">{r.disclaimer}</p>
    </div>
  );
}

export default function Coach() {
  const me = useMe();
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [balance, setBalance] = useState("");
  const [risk, setRisk] = useState("0.5");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Row | null>(null);
  const hist = usePoll<Row[]>("/api/coach/history?limit=20", 60000);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { const urls = files.map((f) => URL.createObjectURL(f)); setPreviews(urls); return () => urls.forEach(URL.revokeObjectURL); }, [files]);
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => { const imgs = Array.from(e.clipboardData?.files || []).filter((f) => f.type.startsWith("image/")); if (imgs.length) add(imgs); };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });
  const add = (list: File[]) => setFiles((f) => [...f, ...list].slice(0, 4));
  const submit = async () => {
    setBusy(true); setErr(null); setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("note", note);
      fd.append("risk_pct", risk);
      if (balance) fd.append("balance", balance);
      const r = await api<Row>("/api/coach/analyze", { method: "POST", body: fd });
      setResult(r); hist.refresh();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="max-w-[1200px] mx-auto">
      <PageHeader title="Chart Coach" subtitle="Send screenshots of your MT5 / TradingView chart (gold or forex). The AI reads the chart, ATLAS checks it against live prices, news and your risk rules, then suggests the move — you place it yourself." />
      <Panel>
        <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add(Array.from(e.dataTransfer.files)); }}
          onClick={() => input.current?.click()}
          className="border-2 border-dashed border-line-2 rounded-xl p-6 text-center cursor-pointer hover:border-accent/50 transition-colors">
          <div className="text-[14px] text-ink">Tap to add chart screenshots</div>
          <div className="text-[12px] text-mute mt-1">or drag & drop / paste · up to 4 images (e.g. M15 + H1) · PNG, JPEG, WebP · 5 MB each</div>
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden" onChange={(e) => { add(Array.from(e.target.files || [])); e.target.value = ""; }} />
        </div>
        {previews.length > 0 && <div className="flex gap-2 mt-3 flex-wrap">{previews.map((u, i) => (
          <div key={u} className="relative"><img src={u} alt={`screenshot ${i + 1}`} className="h-24 rounded-md border border-line-2 object-cover" />
            <button className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-panel-2 border border-line-2 text-[12px]" onClick={() => setFiles((f) => f.filter((_, j) => j !== i))} aria-label="remove">×</button></div>))}</div>}
        <div className="grid sm:grid-cols-[1fr_160px_120px] gap-3 mt-4">
          <label className="block"><span className="label block mb-1">Note (optional)</span>
            <input className="input w-full !h-9" placeholder="e.g. waiting for London open, already long?" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} /></label>
          <label className="block"><span className="label block mb-1">Account balance $</span>
            <input className="input w-full !h-9 num" inputMode="decimal" placeholder="paper equity" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
          <label className="block"><span className="label block mb-1">Risk %</span>
            <select className="input w-full !h-9" value={risk} onChange={(e) => setRisk(e.target.value)}>{["0.25", "0.5", "0.75", "1"].map((x) => <option key={x}>{x}</option>)}</select></label>
        </div>
        <ErrorNote error={err} />
        <button className="btn btn-primary w-full justify-center !h-10 mt-4 text-[14px]" disabled={!files.length || busy || !me?.permissions.trade} onClick={submit}>
          {busy ? "Analysing chart… (up to a minute)" : "Analyse chart"}</button>
        {!me?.permissions.trade && <p className="text-[11.5px] text-mute mt-2">Trader role required.</p>}
      </Panel>
      {result && <div className="mt-3"><ResultCard r={result.result} ts={result.ts} /></div>}
      <div className="label mt-6 mb-2">Previous analyses</div>
      {(hist.data || []).filter((h) => h.id !== result?.id).map((h) => (
        <details key={h.id} className="panel mb-2"><summary className="px-4 py-3 cursor-pointer flex items-center gap-3 text-[12.5px]">
          <span className={`chip border ${finalStyle(h.final)}`}>{h.final}</span><span className="font-semibold">{h.instrument}</span>
          <span className="text-mute">AI: {h.ai_recommendation}</span><span className="flex-1" /><span className="num text-mute text-[11px]">{time(h.ts, true)}</span></summary>
          <div className="p-3 pt-0"><ResultCard r={h.result} /></div></details>))}
      {hist.data && hist.data.length === 0 && !result && <Empty>No analyses yet.</Empty>}
    </div>
  );
}
