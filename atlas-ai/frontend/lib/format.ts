export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function price(v: number | null | undefined, digits?: number): string {
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  const d = digits ?? (a >= 1000 ? 2 : a >= 20 ? 3 : 5);
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export const lots = (v: number | null | undefined) => (isNum(v) ? v.toFixed(2) : "—");
export const pips = (v: number | null | undefined, d = 1) => (isNum(v) ? `${v.toFixed(d)} pips` : "—");

export function usd(v: number | null | undefined, digits = 2): string {
  if (!isNum(v)) return "—";
  return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signedUsd(v: number | null | undefined): string {
  if (!isNum(v)) return "—";
  return (v > 0 ? "+" : "") + usd(v);
}

export function compact(v: number | null | undefined): string {
  if (!isNum(v)) return "—";
  return "$" + Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(v);
}

export function pct(v: number | null | undefined, digits = 2, signed = true): string {
  if (!isNum(v)) return "—";
  return (signed && v > 0 ? "+" : "") + v.toFixed(digits) + "%";
}

export function num(v: number | null | undefined, digits = 2): string {
  return isNum(v) ? v.toLocaleString("en-US", { maximumFractionDigits: digits }) : "—";
}

export function qty(v: number | null | undefined): string {
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  return v.toLocaleString("en-US", { maximumFractionDigits: a >= 1000 ? 0 : a >= 1 ? 4 : 8 });
}

export const tone = (v: number | null | undefined) => (!isNum(v) || v === 0 ? "text-ink-2" : v > 0 ? "text-up" : "text-down");

export function duration(s: number | null | undefined): string {
  if (!isNum(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function time(iso: string | null | undefined, withDate = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return withDate
    ? d.toLocaleString("en-GB", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : d.toLocaleTimeString("en-GB", { hour12: false });
}

export const pair = (s: string) => (s.length === 6 ? `${s.slice(0, 3)}/${s.slice(3)}` : s);
