"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, post } from "@/lib/api";
import { LiveProvider, useLive, usePoll } from "@/lib/live";
import type { Overview } from "@/lib/types";

type Me = { username: string; role: string; permissions: { trade: boolean; admin: boolean } };
const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx);

const NAV = [
  { href: "/", label: "Dashboard", icon: "M3 13h8V3H3v10zm10 8h8V11h-8v10zM3 21h8v-6H3v6zm10-18v6h8V3h-8z" },
  { href: "/markets", label: "Markets · Gold & Forex", icon: "M3 3v18h18M7 14l3-3 3 3 5-6" },
  { href: "/gold", label: "XAU/USD Workspace", icon: "M4 17l3-9h10l3 9H4zm5-9l3-5 3 5" },
  { href: "/terminal", label: "Forex Terminal", icon: "M4 4h16v12H4zM8 20h8M12 16v4" },
  { href: "/analyst", label: "AI Analyst", icon: "M12 3a6 6 0 016 6c0 2.2-1.2 4.1-3 5.2V17H9v-2.8A6 6 0 0112 3zM9 21h6" },
  { href: "/calendar", label: "Economic Calendar", icon: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4" },
  { href: "/activity", label: "Activity Feed", icon: "M3 12h4l3-8 4 16 3-8h4" },
  { href: "/history", label: "Trade Journal", icon: "M5 4h14v16H5zM9 8h6M9 12h6M9 16h4" },
  { href: "/analytics", label: "Performance", icon: "M4 19V9m6 10V5m6 14v-7m4 7H2" },
  { href: "/backtest", label: "Backtesting", icon: "M12 8v4l3 2M21 12a9 9 0 11-3-6.7L21 8M21 3v5h-5" },
  { href: "/settings", label: "Risk, Brokers & Settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1V21a2 2 0 11-4 0v-.1A1.6 1.6 0 009 19.4a1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 003 14H3a2 2 0 110-4h.1A1.6 1.6 0 004.6 9a1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1A1.6 1.6 0 009 4.6V3a2 2 0 114 0v.1a1.6 1.6 0 002.7 1.1l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z" },
];

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" className="w-[16px] h-[16px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

function Dot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2" title={label}>
      <span className={`w-[7px] h-[7px] rounded-full ${ok ? "bg-up shadow-[0_0_6px] shadow-up/60" : "bg-down"}`} />
      <span className="hidden md:inline">{label}</span>
    </span>
  );
}

function TopBar({ me, onMenu }: { me: Me; onMenu: () => void }) {
  const { connected } = useLive();
  const { data, refresh } = usePoll<Overview>("/api/overview", 8000, ["positions"]);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const killed = data?.config.kill_switch;
  const engage = async (action: "keep_protective" | "flatten") => {
    setBusy(true);
    try { await post("/api/control/kill-switch", { engage: true, action }); refresh(); } finally { setBusy(false); setConfirm(false); }
  };
  return (
    <header className="h-12 shrink-0 border-b border-line bg-[#0a0e14]/95 backdrop-blur flex items-center gap-3 px-3 md:px-5 sticky top-0 z-30">
      <button className="md:hidden btn !h-8 !px-2" onClick={onMenu} aria-label="menu">☰</button>
      <span className={`chip ${data?.config.mode === "live" ? "bg-down/15 text-down border-down/30" : data?.config.mode === "demo" ? "bg-warn/12 text-warn border-warn/30" : "bg-accent/12 text-accent border-accent/30"}`}>
        {(data?.config.mode || "paper").toUpperCase()}
      </span>
      <span className="hidden lg:inline text-[11px] text-mute">GOLD &amp; FOREX · data: {data?.config.data_source ?? "—"}</span>
      {killed && <span className="chip bg-down/20 text-down border-down/40 animate-pulse">KILL SWITCH ENGAGED</span>}
      {data && !killed && data.halt && <span className="chip bg-warn/15 text-warn border-warn/30">{data.halt.replace(/_/g, " ").toUpperCase()}</span>}
      <div className="flex-1" />
      <Dot ok={!!data?.agent.alive} label={data?.agent.alive ? "Agent running" : "Agent offline"} />
      <Dot ok={connected} label={connected ? "Live feed" : "Feed reconnecting"} />
      {me.permissions.trade && !killed && (
        confirm ? (
          <span className="flex items-center gap-1.5">
            <button className="btn btn-danger" disabled={busy} onClick={() => engage("keep_protective")} title="Stop all new orders; keep stops/targets on open positions">Halt new orders</button>
            <button className="btn btn-danger" disabled={busy} onClick={() => engage("flatten")} title="Stop all new orders and close every position at market">Halt + flatten</button>
            <button className="btn" onClick={() => setConfirm(false)}>Cancel</button>
          </span>
        ) : (
          <button className="btn btn-danger font-semibold" onClick={() => setConfirm(true)}>■ EMERGENCY STOP</button>
        )
      )}
      <div className="hidden sm:flex items-center gap-2 pl-2 border-l border-line">
        <span className="text-[12px] text-ink-2">{me.username}</span>
        <span className="chip bg-white/[0.04] text-mute border-line-2">{me.role}</span>
        <button className="text-[11.5px] text-mute hover:text-ink" onClick={async () => { await post("/api/auth/logout"); location.href = "/login"; }}>Sign out</button>
      </div>
    </header>
  );
}

function Frame({ me, children }: { me: Me; children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);
  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className={`fixed md:static inset-y-0 left-0 z-40 w-[214px] shrink-0 bg-[#0a0e14] border-r border-line flex flex-col transition-transform ${open ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}>
        <div className="h-12 flex items-center gap-2.5 px-4 border-b border-line">
          <svg viewBox="0 0 24 24" className="w-5 h-5 text-accent" fill="none" stroke="currentColor" strokeWidth={2}><path d="M12 2L2 21h20L12 2zm0 6l5.5 10h-11L12 8z" /></svg>
          <div className="leading-tight">
            <div className="text-[13.5px] font-bold tracking-[0.18em]">ATLAS<span className="text-accent"> AI</span></div>
            <div className="text-[9.5px] text-mute tracking-[0.14em]">GOLD · FOREX</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV.map((n) => {
            const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href}
                className={`flex items-center gap-3 mx-2 px-3 h-9 rounded-md text-[12.8px] transition-colors ${active ? "bg-accent/12 text-ink border border-accent/25" : "text-ink-2 hover:bg-white/[0.03] hover:text-ink border border-transparent"}`}>
                <Icon d={n.icon} />{n.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-line text-[10.5px] text-mute leading-relaxed">
          Trades XAU/USD and forex only. Paper trading by default. Leveraged FX/CFD trading carries a high risk of loss. Not financial advice.
        </div>
      </aside>
      {open && <div className="fixed inset-0 bg-black/60 z-30 md:hidden" onClick={() => setOpen(false)} />}
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar me={me} onMenu={() => setOpen(true)} />
        <main className="flex-1 overflow-y-auto p-3 md:p-5">{children}</main>
      </div>
    </div>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const isLogin = path === "/login";
  useEffect(() => {
    if (isLogin) return;
    api<Me>("/api/auth/me").then(setMe).catch(() => { location.href = "/login"; });
  }, [isLogin]);
  if (isLogin) return <>{children}</>;
  if (!me) return <div className="h-dvh grid place-items-center text-mute text-[12px] tracking-widest">ATLAS AI · AUTHENTICATING…</div>;
  return (
    <MeCtx.Provider value={me}>
      <LiveProvider><Frame me={me}>{children}</Frame></LiveProvider>
    </MeCtx.Provider>
  );
}
