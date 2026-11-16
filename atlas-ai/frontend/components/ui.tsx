"use client";
import { useState, type ReactNode } from "react";

export function Panel({ title, right, children, className = "", pad = true }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`panel flex flex-col min-w-0 ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 px-4 h-11 border-b border-line shrink-0">
          <h2 className="text-[12.5px] font-semibold tracking-wide text-ink">{title}</h2>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={`${pad ? "p-4" : ""} min-h-0 flex-1`}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone = "", hint }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; hint?: string }) {
  return (
    <div className="panel px-4 py-3 min-w-0" title={hint}>
      <div className="label truncate">{label}</div>
      <div className={`num text-[18px] font-semibold mt-1.5 truncate ${tone}`}>{value}</div>
      {sub !== undefined && <div className="num text-[11.5px] text-mute mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

const SIGNAL_STYLE: Record<string, string> = {
  "STRONG BUY CANDIDATE": "bg-up/15 text-up border-up/30",
  "BUY CANDIDATE": "bg-up/10 text-up/90 border-up/20",
  "STRONG SELL CANDIDATE": "bg-down/15 text-down border-down/30",
  "SELL CANDIDATE": "bg-down/10 text-down/90 border-down/20",
  WAIT: "bg-warn/10 text-warn border-warn/25",
  "NO TRADE": "bg-white/[0.03] text-mute border-line-2",
  EXIT: "bg-accent/10 text-accent border-accent/25",
  "HIGH RISK": "bg-down/12 text-down border-down/30",
};
export function SignalChip({ value }: { value: string }) {
  return <span className={`chip ${SIGNAL_STYLE[value] || SIGNAL_STYLE["NO TRADE"]}`}>{value}</span>;
}

export function SideChip({ side }: { side: string | null | undefined }) {
  if (!side) return <span className="text-mute">—</span>;
  const buy = side.toLowerCase() === "buy";
  return <span className={`chip ${buy ? "bg-up/12 text-up border-up/30" : "bg-down/12 text-down border-down/30"}`}>{buy ? "BUY" : "SELL"}</span>;
}

export function Chip({ children, tone = "mute" }: { children: ReactNode; tone?: "up" | "down" | "warn" | "accent" | "mute" }) {
  const t = { up: "bg-up/10 text-up border-up/25", down: "bg-down/10 text-down border-down/25", warn: "bg-warn/10 text-warn border-warn/25",
    accent: "bg-accent/10 text-accent border-accent/25", mute: "bg-white/[0.03] text-ink-2 border-line-2" }[tone];
  return <span className={`chip ${t}`}>{children}</span>;
}

export function RiskChip({ value }: { value: string }) {
  const tone = value === "low" || value === "moderate" ? "up" : value === "medium" || value === "elevated" ? "warn" : value === "unknown" ? "mute" : "down";
  return <Chip tone={tone as "up"}>{value.toUpperCase()}</Chip>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-[12.5px] text-mute py-8 text-center leading-relaxed">{children}</div>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="text-[12px] text-down bg-down/10 border border-down/25 rounded-md px-3 py-2">{error}</div>;
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex p-0.5 rounded-lg bg-[#0a0f15] border border-line-2">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`px-3 h-[26px] rounded-md text-[12px] font-medium transition-colors ${value === o.value ? "bg-panel-2 text-ink border border-line-2" : "text-mute hover:text-ink-2"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 rounded-full border transition-colors disabled:opacity-40 ${checked ? "bg-up/80 border-up" : "bg-[#1a212c] border-line-2"}`}>
      <span className={`absolute top-[1px] h-[14px] w-[14px] rounded-full bg-white transition-transform ${checked ? "translate-x-[15px]" : "translate-x-[1px]"}`} />
    </button>
  );
}

export function Confirm({ label, confirmLabel = "Confirm", onConfirm, className = "btn", disabled, children }:
  { label: ReactNode; confirmLabel?: string; onConfirm: () => Promise<unknown> | void; className?: string; disabled?: boolean; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!open) return <button className={className} disabled={disabled} onClick={() => setOpen(true)}>{label}</button>;
  return (
    <span className="inline-flex items-center gap-1.5">
      {children}
      <button className="btn btn-danger" disabled={busy} onClick={async () => { setBusy(true); try { await onConfirm(); } finally { setBusy(false); setOpen(false); } }}>
        {busy ? "…" : confirmLabel}
      </button>
      <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

export function KV({ k, v, tone = "" }: { k: ReactNode; v: ReactNode; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-[5px] text-[12.5px] border-b border-line/60 last:border-0">
      <span className="text-mute">{k}</span>
      <span className={`num text-right ${tone}`}>{v}</span>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
      <div>
        <h1 className="text-[18px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-[12.5px] text-mute mt-0.5">{subtitle}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}
