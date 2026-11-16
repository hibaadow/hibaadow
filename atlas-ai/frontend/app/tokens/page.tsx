"use client";
import { useState } from "react";
import { useMe } from "@/components/Shell";
import { Chip, Empty, ErrorNote, Panel, PageHeader, RiskChip } from "@/components/ui";
import { post } from "@/lib/api";
import { compact, pct, price, time } from "@/lib/format";
import { usePoll } from "@/lib/live";

type Flag = { code: string; severity: string; message: string; points: number };
type Tok = { id: number; ts: string; mint: string; symbol: string; name: string; dex: string | null; price_usd: number | null; liquidity_usd: number | null; volume_24h: number | null;
  market_cap: number | null; pair_created_at: string | null; top10_holder_pct: number | null; mint_authority: string | null; freeze_authority: string | null;
  risk_score: number; risk_level: string; flags: Flag[]; checks: Record<string, any> };

const sev = (s: string) => (s === "critical" ? "down" : s === "high" ? "down" : s === "medium" ? "warn" : "mute") as "down";

export default function Tokens() {
  const me = useMe();
  const { data, error, refresh } = usePoll<Tok[]>("/api/tokens", 30000, ["tokens"]);
  const [open, setOpen] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader title="Solana New Token Scanner"
        subtitle="Strategy E · discovery via DexScreener, on-chain checks via Solana RPC, honeypot probe via Jupiter. Informational only — never traded automatically."
        right={me?.permissions.trade && <button className="btn" onClick={async () => { await post("/api/tokens/scan"); setMsg("Scan queued — results appear in ~1 minute."); setTimeout(refresh, 45000); }}>Scan now</button>} />
      {msg && <div className="text-[12px] text-ink-2 mb-3">{msg}</div>}
      <ErrorNote error={error} />
      <Panel pad={false}>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Token</th><th>Risk</th><th className="text-right">Score</th><th className="text-right">Price</th><th className="text-right">Liquidity</th><th className="text-right">Volume 24h</th>
              <th className="text-right">Mkt cap</th><th>Pool age</th><th>Mint auth.</th><th>Freeze auth.</th><th className="text-right">Top-10 holders</th><th>Sell route</th><th>Top flags</th></tr></thead>
            <tbody>
              {(data || []).map((t) => {
                const sr = t.checks.sell_route?.status;
                const age = t.checks.market?.pool_age_hours;
                return [
                  <tr key={t.id} className="cursor-pointer" onClick={() => setOpen(open === t.id ? null : t.id)}>
                    <td><div className="font-semibold">{t.symbol}</div><div className="text-[10.5px] text-mute num">{t.mint.slice(0, 6)}…{t.mint.slice(-4)} · {t.dex}</div></td>
                    <td><RiskChip value={t.risk_level} /></td><td className="num text-right">{t.risk_score}</td><td className="num text-right">{price(t.price_usd)}</td>
                    <td className="num text-right">{compact(t.liquidity_usd)}</td><td className="num text-right">{compact(t.volume_24h)}</td><td className="num text-right">{compact(t.market_cap)}</td>
                    <td className="num">{age == null ? "—" : age < 48 ? `${age.toFixed(1)}h` : `${(age / 24).toFixed(0)}d`}</td>
                    <td>{t.checks.mint?.status !== "ok" ? <Chip>UNVERIFIED</Chip> : t.mint_authority ? <Chip tone="down">ACTIVE</Chip> : <Chip tone="up">REVOKED</Chip>}</td>
                    <td>{t.checks.mint?.status !== "ok" ? <Chip>UNVERIFIED</Chip> : t.freeze_authority ? <Chip tone="down">ACTIVE</Chip> : <Chip tone="up">REVOKED</Chip>}</td>
                    <td className="num text-right">{t.top10_holder_pct == null ? <span className="text-mute">n/a</span> : pct(t.checks.holders?.top10_excluding_largest_pct ?? t.top10_holder_pct, 1, false)}</td>
                    <td>{sr === "ok" ? <Chip tone="up">OK</Chip> : sr === "none" ? <Chip tone="down">NONE</Chip> : <Chip>{(sr || "—").toUpperCase()}</Chip>}</td>
                    <td className="max-w-[320px] truncate text-ink-2 text-[11.5px]">{t.flags.slice().sort((a, b) => b.points - a.points).slice(0, 2).map((f) => f.message).join(" · ")}</td>
                  </tr>,
                  open === t.id && (
                    <tr key={`${t.id}-d`}><td colSpan={13} className="!whitespace-normal bg-[#0b1017]">
                      <div className="grid md:grid-cols-2 gap-4 py-2">
                        <div><div className="label mb-1.5">Flags</div>
                          {t.flags.map((f, i) => <div key={i} className="flex gap-2 items-start text-[12px] py-0.5"><Chip tone={sev(f.severity)}>{f.severity.toUpperCase()}</Chip><span className="text-ink-2">{f.message}</span><span className="text-mute num ml-auto">+{f.points}</span></div>)}</div>
                        <div><div className="label mb-1.5">Checks</div><pre className="text-[11px] text-ink-2 num whitespace-pre-wrap break-all">{JSON.stringify(t.checks, null, 1)}</pre>
                          <div className="text-[11px] text-mute mt-2">Scanned {time(t.ts, true)} · mint <span className="num">{t.mint}</span></div></div>
                      </div></td></tr>),
                ];
              })}
            </tbody>
          </table>
          {!data?.length && <Empty>No tokens scanned yet. The scanner runs every few minutes when enabled.</Empty>}
        </div>
      </Panel>
      <p className="text-[11px] text-mute mt-3 max-w-[960px] leading-relaxed">
        Newly launched tokens are extremely high risk. A low score only means none of the automated checks fired — it is never a statement that a token is safe.
        Liquidity lock/burn cannot be verified generically from public APIs and is reported as unverified. Public Solana RPC endpoints rate-limit holder queries; configure a dedicated RPC for complete holder data.
      </p>
    </div>
  );
}
