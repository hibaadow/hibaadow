"use client";
import { useEffect, useState } from "react";
import { useMe } from "@/components/Shell";
import { Chip, Confirm, ErrorNote, Panel, PageHeader, Toggle } from "@/components/ui";
import { api, post, put } from "@/lib/api";
import { time } from "@/lib/format";
import { usePoll } from "@/lib/live";

type Cfg = Record<string, any>;
type SettingsResp = { config: Cfg; strategies: string[]; live_preflight: string[]; live_confirm_phrase: string };
type Integration = { name: string; label: string; purpose: string; status: string; last_ok: string | null; last_error: string | null; latency_ms: number | null; requires_credentials: boolean; configured: boolean };
type Strat = { name: string; label: string; doc: string; enabled: boolean; params: Record<string, number>; defaults: Record<string, number> };

function NumField({ label, value, onChange, step = "0.1", hint, disabled }: { label: string; value: number; onChange: (v: number) => void; step?: string; hint?: string; disabled?: boolean }) {
  return <label className="block"><span className="label block mb-1">{label}</span>
    <input className="input w-full num" type="number" step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
    {hint && <span className="text-[10.5px] text-mute">{hint}</span>}</label>;
}

const statusTone = (s: string) => (s === "ok" ? "up" : s === "degraded" || s === "not armed" ? "warn" : s === "unknown" || s === "unconfigured" || s === "disabled" ? "mute" : "down") as "up";

export default function Settings() {
  const me = useMe();
  const admin = !!me?.permissions.admin;
  const s = usePoll<SettingsResp>("/api/settings", 60000);
  const ints = usePoll<Integration[]>("/api/integrations", 20000);
  const strats = usePoll<Strat[]>("/api/strategies", 60000);
  const audit = usePoll<{ id: number; ts: string; username: string; action: string; target: string | null; ip: string | null }[]>(admin ? "/api/audit?limit=60" : null, 30000);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");
  const [capital, setCapital] = useState(10000);
  const [nu, setNu] = useState({ username: "", password: "", role: "trader" });
  useEffect(() => { if (s.data) setCfg(structuredClone(s.data.config)); }, [s.data]);
  if (!cfg || !s.data) return <div className="text-mute text-[12px]">Loading settings…</div>;
  const set = (path: string, v: unknown) => setCfg((c) => { const n = structuredClone(c!); const ks = path.split("."); let o = n; ks.slice(0, -1).forEach((k) => (o = o[k])); o[ks[ks.length - 1]] = v; return n; });
  const save = async () => {
    setErr(null); setSaved(null);
    try { const body = { ...cfg }; delete body.mode; delete body.kill_switch; delete body.live_confirmed; delete body.trading_enabled;
      await put("/api/settings", body); setSaved("Saved. The agent applies changes within a few seconds."); s.refresh(); }
    catch (e) { setErr((e as Error).message); }
  };
  const r = cfg.risk, a = cfg.automation, fe = cfg.fees, h = cfg.hours;
  return (
    <div className="max-w-[1500px] mx-auto">
      <PageHeader title="Settings & Risk Controls" subtitle={admin ? "Changes are validated server-side; hard ceilings cannot be exceeded." : "Read-only — admin role required to change settings."}
        right={admin && <button className="btn btn-primary" onClick={save}>Save changes</button>} />
      <ErrorNote error={err} />{saved && <div className="text-[12px] text-up mb-3">{saved}</div>}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Panel title="Risk management" className="xl:col-span-2">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <NumField label="Risk per trade %" value={r.risk_per_trade_pct} onChange={(v) => set("risk.risk_per_trade_pct", v)} hint="hard max 1%" disabled={!admin} />
            <NumField label="Max daily loss %" value={r.max_daily_loss_pct} onChange={(v) => set("risk.max_daily_loss_pct", v)} hint="hard max 2%" disabled={!admin} />
            <NumField label="Max weekly loss %" value={r.max_weekly_loss_pct} onChange={(v) => set("risk.max_weekly_loss_pct", v)} hint="hard max 5%" disabled={!admin} />
            <NumField label="Max open positions" value={r.max_open_positions} step="1" onChange={(v) => set("risk.max_open_positions", v)} hint="hard max 3" disabled={!admin} />
            <NumField label="Max portfolio exposure %" value={r.max_portfolio_exposure_pct} step="1" onChange={(v) => set("risk.max_portfolio_exposure_pct", v)} disabled={!admin} />
            <NumField label="Max position exposure %" value={r.max_position_exposure_pct} step="1" onChange={(v) => set("risk.max_position_exposure_pct", v)} disabled={!admin} />
            <NumField label="Min reward : risk" value={r.min_risk_reward} onChange={(v) => set("risk.min_risk_reward", v)} hint="net of costs, min 2" disabled={!admin} />
            <NumField label="Max slippage bps" value={r.max_slippage_bps} step="1" onChange={(v) => set("risk.max_slippage_bps", v)} disabled={!admin} />
            <NumField label="Max spread bps" value={r.max_spread_bps} step="1" onChange={(v) => set("risk.max_spread_bps", v)} disabled={!admin} />
            <NumField label="Losses before cooldown" value={r.consecutive_loss_cooldown} step="1" onChange={(v) => set("risk.consecutive_loss_cooldown", v)} disabled={!admin} />
            <NumField label="Cooldown minutes" value={r.cooldown_minutes} step="15" onChange={(v) => set("risk.cooldown_minutes", v)} disabled={!admin} />
            <NumField label="Max daily trades" value={r.max_daily_trades} step="1" onChange={(v) => set("risk.max_daily_trades", v)} disabled={!admin} />
            <NumField label="Max data staleness s" value={r.max_data_staleness_seconds} step="5" onChange={(v) => set("risk.max_data_staleness_seconds", v)} disabled={!admin} />
            <NumField label="Max venue divergence %" value={r.max_venue_divergence_pct} onChange={(v) => set("risk.max_venue_divergence_pct", v)} disabled={!admin} />
          </div>
          <p className="text-[11px] text-mute mt-3">Every position has a mandatory stop. Size is computed from stop distance including fees and modelled slippage, is halved after two consecutive losses and is never increased to recover losses. Spot only — no margin, leverage or martingale.</p>
        </Panel>
        <Panel title="Trading mode" right={<Chip tone={cfg.mode === "live" ? "down" : "accent"}>{cfg.mode.toUpperCase()}</Chip>}>
          <div className="text-[12px] text-ink-2 space-y-2">
            <div className="flex items-center justify-between"><span>Global trading switch</span>
              <Toggle checked={cfg.trading_enabled} disabled={!me?.permissions.trade || (!admin && !cfg.trading_enabled)} onChange={async (v) => { try { await post("/api/control/trading", { enabled: v }); s.refresh(); } catch (e) { setErr((e as Error).message); } }} /></div>
            <div className="flex items-center justify-between"><span>Kill switch</span>
              {cfg.kill_switch ? (admin ? <Confirm label="Release kill switch" className="btn !h-7" onConfirm={async () => { await post("/api/control/kill-switch", { engage: false }); s.refresh(); }} /> : <Chip tone="down">ENGAGED</Chip>) : <Chip tone="up">OFF</Chip>}</div>
            <div className="pt-3 border-t border-line">
              <div className="label mb-1.5">Live trading preflight</div>
              {s.data.live_preflight.length ? <ul className="text-[11.5px] text-mute list-disc pl-4 space-y-0.5">{s.data.live_preflight.map((p) => <li key={p}>{p}</li>)}</ul> : <div className="text-up text-[12px]">All requirements met.</div>}
              {admin && cfg.mode !== "live" && <div className="mt-3 space-y-2">
                <input className="input w-full" placeholder={`Type: ${s.data.live_confirm_phrase}`} value={phrase} onChange={(e) => setPhrase(e.target.value)} />
                <button className="btn btn-danger w-full justify-center" disabled={phrase !== s.data.live_confirm_phrase} onClick={async () => { try { await post("/api/control/live/arm", { confirm: phrase }); s.refresh(); } catch (e) { setErr((e as Error).message); } }}>Arm live trading</button></div>}
              {cfg.mode === "live" && <button className="btn w-full justify-center mt-3" onClick={async () => { await post("/api/control/live/disarm"); s.refresh(); }}>Return to paper mode</button>}
            </div>
            {admin && <div className="pt-3 border-t border-line"><div className="label mb-1.5">Reset paper account</div>
              <div className="flex gap-2"><input className="input w-full num" type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
                <Confirm label="Reset" onConfirm={async () => { try { await post("/api/control/reset-paper", { capital }); setSaved("Reset queued (requires no open positions)."); } catch (e) { setErr((e as Error).message); } }} /></div></div>}
          </div>
        </Panel>
        <Panel title="Automation">
          <div className="space-y-2.5 text-[12px] text-ink-2">
            {([["scanning_enabled", "Continuous market scanning"], ["signal_generation_enabled", "Automatic signal generation"], ["auto_paper_trading", "Automatic paper trading"],
              ["token_scanner_enabled", "Solana new-token scanner"], ["ai_commentary_enabled", "AI commentary (needs ANTHROPIC_API_KEY)"]] as const).map(([k, l]) => (
              <div key={k} className="flex items-center justify-between"><span>{l}</span><Toggle checked={a[k]} disabled={!admin || (k === "auto_paper_trading" && cfg.kill_switch)} onChange={(v) => set(`automation.${k}`, v)} /></div>))}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <NumField label="Scan interval s" value={a.scan_interval_seconds} step="5" onChange={(v) => set("automation.scan_interval_seconds", v)} disabled={!admin} />
              <NumField label="Token scan interval s" value={a.token_scan_interval_seconds} step="60" onChange={(v) => set("automation.token_scan_interval_seconds", v)} disabled={!admin} />
            </div>
            <p className="text-[11px] text-mute">Open positions are monitored every ~3s even when scanning is paused or the kill switch is engaged.</p>
          </div>
        </Panel>
        <Panel title="Universe & filters">
          <label className="block mb-3"><span className="label block mb-1">Supported assets</span>
            <input className="input w-full num" value={cfg.symbols.join(", ")} disabled={!admin} onChange={(e) => set("symbols", e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean))} /></label>
          <div className="grid grid-cols-2 gap-3">
            <NumField label="Min depth ±1% (USD)" value={cfg.min_liquidity_usd} step="10000" onChange={(v) => set("min_liquidity_usd", v)} disabled={!admin} />
            <NumField label="Min 24h volume (USD)" value={cfg.min_volume_24h_usd} step="100000" onChange={(v) => set("min_volume_24h_usd", v)} disabled={!admin} />
            <NumField label="Min confidence to trade" value={cfg.min_confidence_to_trade} step="1" onChange={(v) => set("min_confidence_to_trade", v)} disabled={!admin} />
            <label className="block"><span className="label block mb-1">Signal timeframe</span>
              <select className="input w-full" value={cfg.primary_timeframe} disabled={!admin} onChange={(e) => set("primary_timeframe", e.target.value)}><option>5m</option><option>15m</option></select></label>
          </div>
          <div className="label mt-3 mb-1.5">Enabled strategies</div>
          {s.data.strategies.map((n) => <label key={n} className="flex items-center justify-between text-[12px] text-ink-2 py-1">{n}
            <Toggle checked={cfg.enabled_strategies.includes(n)} disabled={!admin} onChange={(v) => set("enabled_strategies", v ? [...cfg.enabled_strategies, n] : cfg.enabled_strategies.filter((x: string) => x !== n))} /></label>)}
        </Panel>
        <Panel title="Costs & trading hours">
          <div className="grid grid-cols-2 gap-3">
            <NumField label="Taker fee bps" value={fe.taker_fee_bps} step="0.5" onChange={(v) => set("fees.taker_fee_bps", v)} disabled={!admin} />
            <NumField label="Maker fee bps" value={fe.maker_fee_bps} step="0.5" onChange={(v) => set("fees.maker_fee_bps", v)} disabled={!admin} />
            <NumField label="Base slippage bps" value={fe.base_slippage_bps} step="0.5" onChange={(v) => set("fees.base_slippage_bps", v)} disabled={!admin} />
            <NumField label="Impact coefficient" value={fe.impact_coefficient} step="0.05" onChange={(v) => set("fees.impact_coefficient", v)} hint="bps per 1% of 1-min volume" disabled={!admin} />
            <NumField label="Max participation %" value={fe.max_participation_pct} step="1" onChange={(v) => set("fees.max_participation_pct", v)} hint="partial-fill cap per tick" disabled={!admin} />
          </div>
          <div className="flex items-center justify-between text-[12px] text-ink-2 mt-4"><span>Restrict trading hours (UTC)</span><Toggle checked={h.enabled} disabled={!admin} onChange={(v) => set("hours.enabled", v)} /></div>
          {h.enabled && <div className="grid grid-cols-2 gap-3 mt-2">
            <NumField label="Start hour" value={h.start_hour_utc} step="1" onChange={(v) => set("hours.start_hour_utc", v)} disabled={!admin} />
            <NumField label="End hour" value={h.end_hour_utc} step="1" onChange={(v) => set("hours.end_hour_utc", v)} disabled={!admin} /></div>}
        </Panel>
        <Panel title="Integrations" className="xl:col-span-2" pad={false}>
          <table className="tbl"><thead><tr><th>Service</th><th>Purpose</th><th>Status</th><th className="text-right">Latency</th><th>Last OK</th><th>Last error</th></tr></thead>
            <tbody>{(ints.data || []).map((i) => <tr key={i.name}><td className="font-medium">{i.label}</td><td className="text-ink-2 !whitespace-normal max-w-[280px]">{i.purpose}</td>
              <td><Chip tone={statusTone(i.status)}>{i.status.toUpperCase()}</Chip></td><td className="num text-right">{i.latency_ms ? `${Math.round(i.latency_ms)} ms` : "—"}</td>
              <td className="num text-ink-2">{time(i.last_ok)}</td><td className="text-mute max-w-[260px] truncate" title={i.last_error || ""}>{i.last_error || "—"}</td></tr>)}</tbody></table>
        </Panel>
        <Panel title="Strategy parameters">
          {(strats.data || []).filter((x) => Object.keys(x.params).length).map((st) => (
            <div key={st.name} className="mb-3 pb-3 border-b border-line last:border-0">
              <div className="text-[12.5px] font-semibold">{st.label}</div><div className="text-[11px] text-mute mb-1.5">{st.doc}</div>
              <div className="grid grid-cols-2 gap-2">{Object.entries(st.params).map(([k, v]) => (
                <label key={k} className="text-[11px] text-ink-2">{k}<input className="input w-full num mt-0.5" type="number" step="0.05" defaultValue={v} disabled={!admin}
                  onBlur={async (e) => { const nv = Number(e.target.value); if (nv === v) return; try { await put(`/api/strategies/${st.name}`, { params: { [k]: nv } }); strats.refresh(); setSaved(`${st.label}: ${k}=${nv}`); } catch (er) { setErr((er as Error).message); } }} /></label>))}</div>
            </div>))}
        </Panel>
        {admin && <Panel title="Users">
          <div className="grid grid-cols-3 gap-2">
            <input className="input" placeholder="username" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input className="input" type="password" placeholder="password (10+)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select className="input" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option>viewer</option><option>trader</option><option>admin</option></select>
          </div>
          <button className="btn mt-2" onClick={async () => { try { await post("/api/users", nu); setSaved(`User ${nu.username} created`); setNu({ username: "", password: "", role: "trader" }); } catch (e) { setErr((e as Error).message); } }}>Create user</button>
        </Panel>}
        {admin && <Panel title="Audit log" className="xl:col-span-2" pad={false}>
          <div className="max-h-[320px] overflow-y-auto"><table className="tbl"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>IP</th></tr></thead>
            <tbody>{(audit.data || []).map((x) => <tr key={x.id}><td className="num text-ink-2">{time(x.ts, true)}</td><td>{x.username || "—"}</td><td>{x.action}</td><td className="text-ink-2">{x.target || ""}</td><td className="num text-mute">{x.ip}</td></tr>)}</tbody></table></div>
        </Panel>}
      </div>
    </div>
  );
}
