"use client";
import { useState } from "react";
import { post } from "@/lib/api";

export default function Login() {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try { await post("/api/auth/login", { username: u, password: p }); location.href = "/"; }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="min-h-dvh grid place-items-center px-4 bg-[radial-gradient(ellipse_at_top,#0f1a2e_0%,#080b10_60%)]">
      <form onSubmit={submit} className="panel w-full max-w-[360px] p-6">
        <div className="flex items-center gap-2.5 mb-6">
          <svg viewBox="0 0 24 24" className="w-6 h-6 text-accent" fill="none" stroke="currentColor" strokeWidth={2}><path d="M12 2L2 21h20L12 2zm0 6l5.5 10h-11L12 8z" /></svg>
          <div>
            <div className="text-[15px] font-bold tracking-[0.2em]">ATLAS<span className="text-accent"> AI</span></div>
            <div className="text-[10px] text-mute tracking-[0.16em]">GOLD & FOREX TRADING TERMINAL</div>
          </div>
        </div>
        <label className="label block mb-1.5">Username</label>
        <input className="input w-full mb-3 !h-9" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" autoFocus />
        <label className="label block mb-1.5">Password</label>
        <input className="input w-full mb-4 !h-9" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />
        {err && <div className="text-[12px] text-down mb-3">{err}</div>}
        <button className="btn btn-primary w-full justify-center !h-9" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="text-[10.5px] text-mute mt-5 leading-relaxed">XAU/USD and forex only. Paper trading is the default; broker demo and live accounts require credentials and explicit administrator activation.</p>
      </form>
    </div>
  );
}
