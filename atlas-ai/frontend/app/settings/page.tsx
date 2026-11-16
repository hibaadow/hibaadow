"use client";
import { useEffect, useState } from "react";
import { useMe } from "@/components/Shell";
import { Chip, Confirm, ErrorNote, Panel, PageHeader, Toggle } from "@/components/ui";
import { post, put } from "@/lib/api";
import { time } from "@/lib/format";
import { usePoll } from "@/lib/live";

type Cfg = Record<string, any>;
type Broker = { data_source: string; broker: string; oanda_configured: boolean; oanda_environment: string; mt5_configured: boolean; live_trading_allowed: boolean };
type SettingsResp = { config: Cfg; strategies: string[]; instruments: { symbol: string; display: string; asset_class: string }[]; broker: Broker;
  demo_requirements: string[]; live_requirements: string[]; live_confirm_phrase: string };
type Integration = { name: string; label: string; purpose: string; status: string; last_ok: string | null; last_error: string | null; latency_ms: number | null; requires_credentials: boolean; configured: boolean };
type Strat = { name: string; label: string; doc: string; enabled: boolean; instruments: string[] | "all"; params: Record<string, number> };

function NumField({ label, value, onChange, step = "0.1", hint, disabled }: { label: string; value: number; onChange: (v: number) => void; step?: string; hint?: string; disabled?: boolean }) {
  return <label className="block"><span className="label block mb-1">{label}</span>
    <input className="input w-full num" type="number" step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
    {hint && <span className="text-[10.5px] text-mute">{hint}</span>}</label>;
}

const statusTone = (s: string) => (s === "ok" ? "up" : s === "degraded" ? "warn" : s === "unknown" || s === "unconfigured" ? "mute" : "down") as "up";

export default function Settings() {
  const me = useMe();
  const admin = !!me?.permissions.admin;
  const s = usePoll<SettingsResp>("/api/settings", 60000);
  const ints = usePoll<{ integrations: Integration[] }>("/api/integrations", 20000);
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
  const act = async (fn: () => Promise<unknown>, ok?: string) => { setErr(null); try { await fn(); if (ok) setSaved(ok); s.refresh(); } catch (e) { setErr((e as Error).message); } };
  const save = () => act(async () => { const body = { ...cfg }; for (const k of ["mode", "kill_switch", "live_confirmed", "trading_enabled"]) delete body[k]; await put("/api/settings", body); },
    "Saved. The agent applies changes within a few seconds.");
  const r = cfg.risk, a = cfg.automation, c = cfg.costs, n = cfg.news, se = cfg.sessions, b = s.data.broker;
  return (
    <div className="max-w-[1500px] mx-auto">
      <PageHeader title="Risk, Brokers & Settings" subtitle={admin ? "Validated server-side; hard ceilings cannot be exceeded. Only XAU/USD and forex can be configured." : "Read-only — admin role required."}
        right={admin && <button className="btn btn-primary" onClick={save}>Save changes</button>} />
      <ErrorNote error={err} />{saved && <div className="text-[12px] text-up mb-3">{saved}</div>}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Panel title="Risk management" className="xl:col-span-2">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <NumField label="Risk per trade %" value={r.risk_per_trade_pct} onChange={(v) => set("risk.risk_per_trade_pct", v)} hint="default 0.5 · max 1" disabled={!admin} />
            <NumField label="Max daily loss %" value={r.max_daily_loss_pct} onChange={(v) => set("risk.max_daily_loss_pct", v)} hint="max 2" disabled={!admin} />
            <NumField label="Max weekly loss %" value={r.max_weekly_loss_pct} onChange={(v) => set("risk.max_weekly_loss_pct", v)} hint="max 5" disabled={!admin} />
            <NumField label="Max open positions" value={r.max_open_positions} step="1" onChange={(v) => set("risk.max_open_positions", v)} hint="max 3" disabled={!admin} />
            <NumField label="Min reward : risk (net)" value={r.min_risk_reward} onChange={(v) => set("risk.min_risk_reward", v)} hint="min 2 after costs" disabled={!admin} />
            <NumField label="Max risk per currency %" value={r.max_risk_per_currency_pct} onChange={(v) => set("risk.max_risk_per_currency_pct", v)} hint="net directional" disabled={!admin} />
            <NumField label="Max effective leverage" value={r.max_effective_leverage} step="1" onChange={(v) => set("risk.max_effective_leverage", v)} hint="total notional / equity" disabled={!admin} />
            <NumField label="Min margin level %" value={r.min_margin_level_pct} step="10" onChange={(v) => set("risk.min_margin_level_pct", v)} disabled={!admin} />
            <NumField label="Losses before cooldown" value={r.consecutive_loss_cooldown} step="1" onChange={(v) => set("risk.consecutive_loss_cooldown", v)} disabled={!admin} />
            <NumField label="Cooldown minutes" value={r.cooldown_minutes} step="15" onChange={(v) => set("risk.cooldown_minutes", v)} disabled={!admin} />
            <NumField label="Max daily trades" value={r.max_daily_trades} step="1" onChange={(v) => set("risk.max_daily_trades", v)} disabled={!admin} />
            <NumField label="Max quote age (s)" value={r.max_data_staleness_seconds} step="5" onChange={(v) => set("risk.max_data_staleness_seconds", v)} disabled={!admin} />
          </div>
          <div className="label mt-4 mb-1.5">Per-instrument spread & slippage limits (pips)</div>
          <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Instrument</th>{s.data.instruments.map((i) => <th key={i.symbol} className="text-right">{i.display}</th>)}</tr></thead>
            <tbody>{(["spread_limits_pips", "max_slippage_pips"] as const).map((k) => <tr key={k}><td className="text-ink-2">{k === "spread_limits_pips" ? "Max spread" : "Max slippage"}</td>
              {s.data!.instruments.map((i) => <td key={i.symbol} className="text-right"><input className="input w-[64px] num text-right" type="number" step="0.1" disabled={!admin}
                value={r[k][i.symbol] ?? ""} onChange={(e) => set(`risk.${k}`, { ...r[k], [i.symbol]: Number(e.target.value) })} /></td>)}</tr>)}</tbody></table></div>
          <p className="text-[11px] text-mute mt-3">Lots = risk ÷ (stop pips + stop slippage) × pip value + commission, rounded DOWN to the lot step. Size is halved after two consecutive losses and never increased to recover losses — no martingale. Gold: 1 lot = 100 oz, pip = $0.10. FX: 1 lot = 100,000 base units.</p>
        </Panel>

        <Panel title="Trading mode & broker" right={<Chip tone={cfg.mode === "live" ? "down" : cfg.mode === "demo" ? "warn" : "accent"}>{cfg.mode.toUpperCase()}</Chip>}>
          <div className="text-[12px] text-ink-2 space-y-2">
            <div className="flex justify-between"><span>Data source</span><span className="num">{b.data_source}</span></div>
            <div className="flex justify-between"><span>Broker</span><span className="num">{b.broker}{b.broker === "oanda" ? ` (${b.oanda_environment})` : ""}</span></div>
            <div className="flex justify-between"><span>OANDA credentials</span>{b.oanda_configured ? <Chip tone="up">SET</Chip> : <Chip>NOT SET</Chip>}</div>
            <div className="flex justify-between"><span>MT5 bridge</span>{b.mt5_configured ? <Chip tone="up">SET</Chip> : <Chip>NOT SET</Chip>}</div>
            <div className="flex items-center justify-between pt-2 border-t border-line"><span>Global trading switch</span>
              <Toggle checked={cfg.trading_enabled} disabled={!me?.permissions.trade || (!admin && !cfg.trading_enabled)} onChange={(v) => act(() => post("/api/control/trading", { enabled: v }))} /></div>
            <div className="flex items-center justify-between"><span>Emergency stop</span>
              {cfg.kill_switch ? (admin ? <Confirm label="Release" className="btn !h-7" onConfirm={() => act(() => post("/api/control/kill-switch", { engage: false }))} /> : <Chip tone="down">ENGAGED</Chip>) : <Chip tone="up">OFF</Chip>}</div>
            {admin && <div className="pt-2 border-t border-line space-y-2">
              <div className="flex gap-2">
                <button className="btn flex-1 justify-center" disabled={cfg.mode === "paper"} onClick={() => act(() => post("/api/control/mode", { mode: "paper" }), "Switched to paper")}>Paper</button>
                <button className="btn flex-1 justify-center" disabled={cfg.mode === "demo"} onClick={() => act(() => post("/api/control/mode", { mode: "demo" }), "Switched to broker demo")}>Broker demo</button>
              </div>
              {s.data.demo_requirements.length > 0 && <ul className="text-[11px] text-mute list-disc pl-4">{s.data.demo_requirements.map((x) => <li key={x}>{x}</li>)}</ul>}
              <div className="label pt-2">Live account (real money)</div>
              {s.data.live_requirements.length ? <ul className="text-[11px] text-mute list-disc pl-4">{s.data.live_requirements.map((x) => <li key={x}>{x}</li>)}</ul> : <div className="text-[11.5px] text-warn">All live requirements met.</div>}
              {cfg.mode !== "live" ? <>
                <input className="input w-full" placeholder={`Type: ${s.data.live_confirm_phrase}`} value={phrase} onChange={(e) => setPhrase(e.target.value)} />
                <button className="btn btn-danger w-full justify-center" disabled={phrase !== s.data.live_confirm_phrase} onClick={() => act(() => post("/api/control/live/arm", { confirm: phrase }), "Live armed (automatic trading left OFF)")}>Arm live trading</button>
              </> : <button className="btn w-full justify-center" onClick={() => act(() => post("/api/control/live/disarm"), "Back to paper")}>Disarm live → paper</button>}
            </div>}
            {admin && <div className="pt-2 border-t border-line"><div className="label mb-1.5">Reset paper account</div>
              <div className="flex gap-2"><input className="input w-full num" type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
                <Confirm label="Reset" onConfirm={() => act(() => post("/api/control/reset-paper", { capital }), "Reset queued (needs no open paper positions)")} /></div></div>}
          </div>
        </Panel>

        <Panel title="News & session filters">
          <div className="space-y-2.5 text-[12px] text-ink-2">
            <div className="flex items-center justify-between"><span>High-impact news blackout</span><Toggle checked={n.enabled} disabled={!admin} onChange={(v) => set("news.enabled", v)} /></div>
            <div className="grid grid-cols-3 gap-2">
              <NumField label="Min before" value={n.minutes_before} step="5" onChange={(v) => set("news.minutes_before", v)} disabled={!admin} />
              <NumField label="Min after" value={n.minutes_after} step="5" onChange={(v) => set("news.minutes_after", v)} disabled={!admin} />
              <NumField label="CB extra" value={n.central_bank_extra_minutes} step="5" onChange={(v) => set("news.central_bank_extra_minutes", v)} disabled={!admin} />
            </div>
            <div className="flex items-center justify-between"><span>Flatten before high-impact events</span><Toggle checked={n.flatten_before_high_impact} disabled={!admin} onChange={(v) => set("news.flatten_before_high_impact", v)} /></div>
            <div className="label pt-2">Allowed sessions for new trades</div>
            {["Sydney", "Tokyo", "London", "New York"].map((x) => <div key={x} className="flex items-center justify-between"><span>{x}</span>
              <Toggle checked={se.allowed_sessions.includes(x)} disabled={!admin} onChange={(v) => set("sessions.allowed_sessions", v ? [...se.allowed_sessions, x] : se.allowed_sessions.filter((y: string) => y !== x))} /></div>)}
            <div className="flex items-center justify-between"><span>JPY/AUD/NZD pairs may trade in Asia</span><Toggle checked={se.allow_asia_for_asia_pairs} disabled={!admin} onChange={(v) => set("sessions.allow_asia_for_asia_pairs", v)} /></div>
            <div className="flex items-center justify-between"><span>Avoid daily rollover</span><Toggle checked={se.avoid_rollover} disabled={!admin} onChange={(v) => set("sessions.avoid_rollover", v)} /></div>
            <div className="flex items-center justify-between"><span>Flat before the weekend</span><Toggle checked={se.close_before_weekend} disabled={!admin} onChange={(v) => set("sessions.close_before_weekend", v)} /></div>
          </div>
        </Panel>

        <Panel title="Automation & instruments">
          <div className="space-y-2.5 text-[12px] text-ink-2">
            {([["scanning_enabled", "Continuous market analysis"], ["signal_generation_enabled", "Signal generation"], ["auto_trading", "Automatic trading (current mode)"],
              ["ai_commentary_enabled", "AI commentary (needs ANTHROPIC_API_KEY)"]] as const).map(([k, l]) => (
              <div key={k} className="flex items-center justify-between"><span>{l}</span><Toggle checked={a[k]} disabled={!admin || (k === "auto_trading" && cfg.kill_switch)} onChange={(v) => set(`automation.${k}`, v)} /></div>))}
            <NumField label="Analysis interval (s)" value={a.scan_interval_seconds} step="5" onChange={(v) => set("automation.scan_interval_seconds", v)} disabled={!admin} />
            <div className="label pt-2">Traded instruments</div>
            {(["gold", "forex"] as const).map((ac) => <div key={ac}><div className="text-[11px] text-mute uppercase tracking-wider mt-1">{ac}</div>
              <div className="flex flex-wrap gap-1.5 mt-1">{s.data!.instruments.filter((i) => i.asset_class === ac).map((i) => {
                const on = cfg.symbols.includes(i.symbol);
                return <button key={i.symbol} disabled={!admin} onClick={() => set("symbols", on ? cfg.symbols.filter((x: string) => x !== i.symbol) : [...cfg.symbols, i.symbol])}
                  className={`chip border ${on ? "bg-accent/15 text-accent border-accent/30" : "bg-white/[0.03] text-mute border-line-2"}`}>{i.display}</button>;
              })}</div></div>)}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <NumField label="Min confidence to trade" value={cfg.min_confidence_to_trade} step="1" onChange={(v) => set("min_confidence_to_trade", v)} disabled={!admin} />
              <label className="block"><span className="label block mb-1">Entry timeframe</span>
                <select className="input w-full" value={cfg.primary_timeframe} disabled={!admin} onChange={(e) => set("primary_timeframe", e.target.value)}><option>5m</option><option>15m</option></select></label>
            </div>
          </div>
        </Panel>

        <Panel title="Costs & paper account">
          <div className="grid grid-cols-2 gap-3">
            <NumField label="FX commission $/lot/side" value={c.commission_per_lot_side_usd} step="0.5" onChange={(v) => set("costs.commission_per_lot_side_usd", v)} disabled={!admin} />
            <NumField label="Gold commission $/lot/side" value={c.gold_commission_per_lot_side_usd} step="0.5" onChange={(v) => set("costs.gold_commission_per_lot_side_usd", v)} disabled={!admin} />
            <NumField label="Slippage multiplier" value={c.slippage_multiplier} step="0.1" onChange={(v) => set("costs.slippage_multiplier", v)} disabled={!admin} />
            <NumField label="News slippage multiplier" value={c.news_slippage_multiplier} step="0.5" onChange={(v) => set("costs.news_slippage_multiplier", v)} disabled={!admin} />
            <NumField label="Paper leverage cap" value={cfg.paper_leverage} step="1" onChange={(v) => set("paper_leverage", v)} hint="≤ 30:1" disabled={!admin} />
          </div>
          <div className="label mt-4 mb-1.5">Enabled strategies</div>
          {s.data.strategies.map((x) => <label key={x} className="flex items-center justify-between text-[12px] text-ink-2 py-1">{x}
            <Toggle checked={cfg.enabled_strategies.includes(x)} disabled={!admin} onChange={(v) => set("enabled_strategies", v ? [...cfg.enabled_strategies, x] : cfg.enabled_strategies.filter((y: string) => y !== x))} /></label>)}
        </Panel>

        <Panel title="Integrations" className="xl:col-span-2" pad={false}>
          <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Service</th><th>Purpose</th><th>Credentials</th><th>Status</th><th className="text-right">Latency</th><th>Last OK</th><th>Last error</th></tr></thead>
            <tbody>{(ints.data?.integrations || []).map((i) => <tr key={i.name}><td className="font-medium">{i.label}</td><td className="text-ink-2 !whitespace-normal max-w-[280px]">{i.purpose}</td>
              <td>{i.requires_credentials ? (i.configured ? <Chip tone="up">SET</Chip> : <Chip tone="warn">REQUIRED</Chip>) : <Chip>NONE NEEDED</Chip>}</td>
              <td><Chip tone={statusTone(i.status)}>{i.status.toUpperCase()}</Chip></td><td className="num text-right">{i.latency_ms ? `${Math.round(i.latency_ms)} ms` : "—"}</td>
              <td className="num text-ink-2">{time(i.last_ok)}</td><td className="text-mute max-w-[240px] truncate" title={i.last_error || ""}>{i.last_error || "—"}</td></tr>)}</tbody></table></div>
        </Panel>

        <Panel title="Strategy parameters">
          {(strats.data || []).map((st) => (
            <div key={st.name} className="mb-3 pb-3 border-b border-line last:border-0">
              <div className="text-[12.5px] font-semibold">{st.label} {st.instruments !== "all" && <Chip tone="warn">{(st.instruments as string[]).join(", ")} only</Chip>}</div>
              <div className="text-[11px] text-mute mb-1.5">{st.doc}</div>
              <div className="grid grid-cols-2 gap-2">{Object.entries(st.params).map(([k, v]) => (
                <label key={k} className="text-[11px] text-ink-2">{k}<input className="input w-full num mt-0.5" type="number" step="0.05" defaultValue={v} disabled={!admin}
                  onBlur={async (e) => { const nv = Number(e.target.value); if (nv === v) return; await act(() => put(`/api/strategies/${st.name}`, { params: { [k]: nv } }), `${st.label}: ${k}=${nv}`); strats.refresh(); }} /></label>))}</div>
            </div>))}
        </Panel>

        {admin && <Panel title="Users">
          <div className="grid grid-cols-3 gap-2">
            <input className="input" placeholder="username" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input className="input" type="password" placeholder="password (10+)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select className="input" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option>viewer</option><option>trader</option><option>admin</option></select>
          </div>
          <button className="btn mt-2" onClick={() => act(async () => { await post("/api/users", nu); setNu({ username: "", password: "", role: "trader" }); }, `User ${nu.username} created`)}>Create user</button>
        </Panel>}
        {admin && <Panel title="Audit log" className="xl:col-span-2" pad={false}>
          <div className="max-h-[320px] overflow-y-auto"><table className="tbl"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>IP</th></tr></thead>
            <tbody>{(audit.data || []).map((x) => <tr key={x.id}><td className="num text-ink-2">{time(x.ts, true)}</td><td>{x.username || "—"}</td><td>{x.action}</td><td className="text-ink-2">{x.target || ""}</td><td className="num text-mute">{x.ip}</td></tr>)}</tbody></table></div>
        </Panel>}
      </div>
    </div>
  );
}
