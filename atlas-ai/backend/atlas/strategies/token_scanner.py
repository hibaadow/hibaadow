"""Strategy E — Solana new-token scanner.

Discovers newly listed Solana tokens (DexScreener), then runs on-chain and
market-structure safety checks:

* mint authority / freeze authority (Solana RPC, jsonParsed mint account)
* Token-2022 extensions that enable transfer restrictions or fees
  (transferFeeConfig, transferHook, permanentDelegate, nonTransferable, defaultAccountState)
* holder concentration (getTokenLargestAccounts; public RPCs often rate-limit this — reported as unverified)
* liquidity, volume, pool age
* buy/sell imbalance, average trade size and volume/liquidity ratio (wash trading signals)
* sell-route existence and price impact via a Jupiter quote (honeypot signal)
* liquidity lock / burn: NOT generally verifiable from public APIs; reported as unverified

Results are informational. This scanner NEVER produces tradeable signals:
newly discovered tokens are not automatically traded.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..config import get_settings
from ..logging import get_logger
from ..marketdata.http import ProviderClient, ProviderError

log = get_logger("atlas.tokenscan")

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")
RISKY_EXTENSIONS = {"transferFeeConfig": "transfer fee (tax) configured", "transferHook": "transfer hook can block/alter transfers",
                    "permanentDelegate": "permanent delegate can move holders' tokens", "nonTransferable": "token is non-transferable",
                    "defaultAccountState": "accounts may be frozen by default", "pausableConfig": "transfers can be paused"}


def sanitize_text(s, max_len: int = 64) -> str:
    """Neutralise untrusted token metadata (HTML/JS injection, control/bidi chars)."""
    if not isinstance(s, str):
        return ""
    s = _CTRL.sub("", s)
    s = html.escape(s.strip(), quote=True)
    return s[:max_len]


def sanitize_url(u) -> str | None:
    if not isinstance(u, str) or len(u) > 300:
        return None
    p = urlparse(u)
    if p.scheme != "https" or not p.netloc:
        return None
    return u


def valid_mint(m: str) -> bool:
    return isinstance(m, str) and bool(_B58.match(m))


@dataclass
class TokenReport:
    mint: str
    symbol: str = ""
    name: str = ""
    pair_address: str | None = None
    dex: str | None = None
    price_usd: float | None = None
    liquidity_usd: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    fdv: float | None = None
    pair_created_at: datetime | None = None
    top10_holder_pct: float | None = None
    mint_authority: str | None = None
    freeze_authority: str | None = None
    flags: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    risk_score: int = 0  # 0 (lowest observed risk) .. 100 (extreme)
    risk_level: str = "unknown"

    def flag(self, code: str, severity: str, message: str, points: int) -> None:
        self.flags.append({"code": code, "severity": severity, "message": message, "points": points})


def score(report: TokenReport) -> TokenReport:
    pts = sum(f["points"] for f in report.flags)
    report.risk_score = int(max(0, min(100, pts)))
    critical = any(f["severity"] == "critical" for f in report.flags)
    if critical or report.risk_score >= 70:
        report.risk_level = "extreme"
    elif report.risk_score >= 45:
        report.risk_level = "high"
    elif report.risk_score >= 25:
        report.risk_level = "elevated"
    else:
        report.risk_level = "moderate"  # never "safe": new tokens are inherently high risk
    return report


def assess_market(report: TokenReport, pair: dict, now: float | None = None) -> None:
    """Market-structure checks on a DexScreener pair object."""
    now = now or time.time()
    liq = (pair.get("liquidity") or {}).get("usd")
    vol = (pair.get("volume") or {}).get("h24")
    tx = (pair.get("txns") or {}).get("h24") or {}
    tx1 = (pair.get("txns") or {}).get("h1") or {}
    buys, sells = int(tx.get("buys") or 0), int(tx.get("sells") or 0)
    created = pair.get("pairCreatedAt")
    report.checks["market"] = {"liquidity_usd": liq, "volume_24h": vol, "buys_24h": buys, "sells_24h": sells,
                               "buys_1h": tx1.get("buys"), "sells_1h": tx1.get("sells")}
    if liq is None or liq < 10_000:
        report.flag("low_liquidity", "high", f"liquidity ${liq or 0:,.0f} below $10k", 25)
    elif liq < 50_000:
        report.flag("thin_liquidity", "medium", f"liquidity ${liq:,.0f} below $50k", 10)
    if created:
        age_h = (now * 1000 - created) / 3_600_000
        report.checks["market"]["pool_age_hours"] = round(age_h, 2)
        if age_h < 24:
            report.flag("very_new_pool", "medium", f"pool is {age_h:.1f}h old", 15)
    if buys + sells > 50:
        if sells == 0:
            report.flag("no_sells", "critical", f"{buys} buys and zero sells in 24h — honeypot pattern", 60)
        elif buys / max(sells, 1) > 6:
            report.flag("buy_sell_imbalance", "high", f"buy/sell ratio {buys / sells:.1f} — possible sell restriction", 25)
    if liq and vol:
        turnover = vol / liq
        report.checks["market"]["turnover"] = round(turnover, 2)
        if turnover > 40:
            report.flag("wash_trading_turnover", "high", f"24h volume is {turnover:.0f}x liquidity — wash trading indicator", 20)
    if vol and buys + sells > 0:
        avg = vol / (buys + sells)
        report.checks["market"]["avg_trade_usd"] = round(avg, 2)
        if avg < 5 and buys + sells > 5_000:
            report.flag("micro_trades", "medium", f"avg trade ${avg:.2f} across {buys + sells} txns — bot/wash pattern", 10)
    pc = pair.get("priceChange") or {}
    if isinstance(pc.get("h1"), (int, float)) and abs(pc["h1"]) > 80:
        report.flag("extreme_volatility", "high", f"price moved {pc['h1']:+.0f}% in 1h", 15)


def assess_mint(report: TokenReport, info: dict | None, owner: str | None) -> None:
    if info is None:
        report.checks["mint"] = {"status": "unavailable"}
        report.flag("mint_unverified", "medium", "mint account could not be read", 15)
        return
    parsed = info.get("info", {}) if isinstance(info, dict) else {}
    report.mint_authority = parsed.get("mintAuthority")
    report.freeze_authority = parsed.get("freezeAuthority")
    report.checks["mint"] = {"status": "ok", "program": "token-2022" if owner == TOKEN_2022 else "spl-token",
                             "decimals": parsed.get("decimals"), "supply": parsed.get("supply"),
                             "mint_authority": report.mint_authority, "freeze_authority": report.freeze_authority}
    if report.mint_authority:
        report.flag("mint_authority", "critical", "mint authority is active — supply can be inflated", 40)
    if report.freeze_authority:
        report.flag("freeze_authority", "critical", "freeze authority is active — holders can be frozen (honeypot risk)", 40)
    exts = parsed.get("extensions") or []
    names = [e.get("extension") for e in exts if isinstance(e, dict)]
    report.checks["mint"]["extensions"] = names
    for e in exts:
        name = e.get("extension") if isinstance(e, dict) else None
        if name in RISKY_EXTENSIONS:
            sev = "critical" if name in ("permanentDelegate", "nonTransferable", "transferHook", "pausableConfig") else "high"
            msg = RISKY_EXTENSIONS[name]
            if name == "transferFeeConfig":
                try:
                    bps = int(e["state"]["newerTransferFee"]["transferFeeBasisPoints"])
                    msg = f"transfer tax {bps / 100:.2f}%"
                    sev = "critical" if bps >= 500 else ("high" if bps > 0 else "low")
                    if bps == 0:
                        continue
                except (KeyError, TypeError, ValueError):
                    pass
            report.flag(f"ext_{name}", sev, msg, 40 if sev == "critical" else 20)


def assess_holders(report: TokenReport, largest: list[dict] | None, supply_raw: str | None, decimals: int | None) -> None:
    if largest is None or not supply_raw:
        report.checks["holders"] = {"status": "unavailable"}
        report.flag("holders_unverified", "medium", "holder concentration not verifiable (RPC limit)", 10)
        return
    try:
        supply = int(supply_raw)
        top = sorted((int(a["amount"]) for a in largest), reverse=True)
    except (KeyError, TypeError, ValueError):
        report.checks["holders"] = {"status": "invalid"}
        return
    if supply <= 0:
        return
    # NOTE: the largest account is frequently the AMM pool vault, so we report both
    top10 = sum(top[:10]) / supply * 100
    top10_ex_first = sum(top[1:11]) / supply * 100
    report.top10_holder_pct = round(top10, 2)
    report.checks["holders"] = {"status": "ok", "top10_pct": round(top10, 2), "top10_excluding_largest_pct": round(top10_ex_first, 2),
                                "largest_pct": round(top[0] / supply * 100, 2) if top else None,
                                "note": "largest account may be a liquidity pool vault"}
    if top10_ex_first > 50:
        report.flag("holder_concentration", "high", f"top holders (ex-largest) own {top10_ex_first:.0f}% of supply", 25)
    elif top10_ex_first > 30:
        report.flag("holder_concentration", "medium", f"top holders (ex-largest) own {top10_ex_first:.0f}% of supply", 12)


def assess_sell_route(report: TokenReport, quote: dict | None, error: str | None) -> None:
    if quote is None:
        report.checks["sell_route"] = {"status": "none", "error": error}
        report.flag("no_sell_route", "critical", f"no Jupiter sell route to USDC ({error or 'unavailable'})", 45)
        return
    try:
        impact = float(quote.get("priceImpactPct") or 0) * 100
    except (TypeError, ValueError):
        impact = None
    report.checks["sell_route"] = {"status": "ok", "price_impact_pct": impact, "hops": len(quote.get("routePlan") or [])}
    if impact is not None and impact > 5:
        report.flag("sell_impact", "high", f"selling ~$100 has {impact:.1f}% price impact", 20)


class TokenScanner:
    name = "solana_new_token"

    def __init__(self):
        s = get_settings()
        self.dex = ProviderClient("dexscreener", s.dexscreener_url, rate_per_sec=1, burst=3)
        self.jup = ProviderClient("jupiter", s.jupiter_url, rate_per_sec=0.8, burst=2)
        self.rpc = ProviderClient("solana_rpc", s.solana_rpc_url, rate_per_sec=1, burst=2, max_retries=1)

    async def close(self):
        for c in (self.dex, self.jup, self.rpc):
            await c.close()

    async def _rpc(self, method: str, params: list):
        d = await self.rpc.post("", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(d, dict) or "error" in d:
            raise ProviderError("solana_rpc", str((d or {}).get("error"))[:160] if isinstance(d, dict) else "bad response")
        return d.get("result")

    async def discover(self, limit: int = 15) -> list[str]:
        """Latest Solana token mints from DexScreener profiles + boosts."""
        mints: list[str] = []
        for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
            try:
                rows = await self.dex.get(path)
            except ProviderError as e:
                log.warning("dexscreener discovery failed", extra={"data": {"path": path, "error": str(e)}})
                continue
            for r in rows if isinstance(rows, list) else []:
                m = r.get("tokenAddress")
                if r.get("chainId") == "solana" and valid_mint(m) and m not in mints:
                    mints.append(m)
        return mints[:limit]

    async def pairs_for(self, mints: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(mints), 30):
            chunk = [m for m in mints[i:i + 30] if valid_mint(m)]
            if not chunk:
                continue
            rows = await self.dex.get(f"/tokens/v1/solana/{','.join(chunk)}")
            for p in rows if isinstance(rows, list) else []:
                base = (p.get("baseToken") or {}).get("address")
                if base in chunk:
                    best = out.get(base)
                    if best is None or ((p.get("liquidity") or {}).get("usd") or 0) > ((best.get("liquidity") or {}).get("usd") or 0):
                        out[base] = p
        return out

    async def analyze(self, mint: str, pair: dict | None) -> TokenReport:
        rep = TokenReport(mint=mint)
        if pair:
            bt = pair.get("baseToken") or {}
            rep.symbol = sanitize_text(bt.get("symbol"), 24)
            rep.name = sanitize_text(bt.get("name"), 64)
            rep.pair_address = pair.get("pairAddress") if valid_mint(pair.get("pairAddress", "")) else None
            rep.dex = sanitize_text(pair.get("dexId"), 24)
            for attr, key in (("price_usd", "priceUsd"), ("fdv", "fdv"), ("market_cap", "marketCap")):
                try:
                    setattr(rep, attr, float(pair.get(key)) if pair.get(key) is not None else None)
                except (TypeError, ValueError):
                    pass
            rep.liquidity_usd = (pair.get("liquidity") or {}).get("usd")
            rep.volume_24h = (pair.get("volume") or {}).get("h24")
            if pair.get("pairCreatedAt"):
                rep.pair_created_at = datetime.fromtimestamp(pair["pairCreatedAt"] / 1000, timezone.utc)
            info = pair.get("info") or {}
            rep.checks["metadata"] = {"website": next((sanitize_url(w.get("url")) for w in info.get("websites") or [] if isinstance(w, dict)), None),
                                      "socials": len(info.get("socials") or [])}
            if not info.get("websites") and not info.get("socials"):
                rep.flag("no_socials", "low", "no website or social links in metadata", 5)
            assess_market(rep, pair)
        else:
            rep.flag("no_pair", "high", "no DEX pair data found", 30)
        # On-chain mint checks
        supply = decimals = None
        try:
            acct = await self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
            val = (acct or {}).get("value") or {}
            parsed = (val.get("data") or {}).get("parsed") if isinstance(val.get("data"), dict) else None
            assess_mint(rep, parsed, val.get("owner"))
            if parsed:
                supply = parsed.get("info", {}).get("supply")
                decimals = parsed.get("info", {}).get("decimals")
        except ProviderError as e:
            assess_mint(rep, None, None)
            rep.checks["mint"]["error"] = str(e)[:120]
        try:
            largest = await self._rpc("getTokenLargestAccounts", [mint])
            assess_holders(rep, (largest or {}).get("value"), supply, decimals)
        except ProviderError:
            assess_holders(rep, None, None, None)
        # Honeypot probe: does a sell route exist? Quote ~$100 worth (needs price + decimals)
        if rep.price_usd and decimals is not None and rep.price_usd > 0:
            amount = int(100 / rep.price_usd * (10 ** int(decimals)))
            try:
                q = await self.jup.get("/swap/v1/quote", inputMint=mint, outputMint=USDC_MINT, amount=max(amount, 1), slippageBps=300)
                if isinstance(q, dict) and q.get("outAmount"):
                    assess_sell_route(rep, q, None)
                else:
                    assess_sell_route(rep, None, (q or {}).get("error") if isinstance(q, dict) else "bad response")
            except ProviderError as e:
                assess_sell_route(rep, None, str(e)[:120])
        else:
            rep.checks["sell_route"] = {"status": "skipped", "reason": "price or decimals unknown"}
        rep.checks["liquidity_lock"] = {"status": "unverified",
                                        "note": "LP lock/burn cannot be verified generically from public APIs; treat as unlocked"}
        rep.flag("lp_unverified", "low", "liquidity lock/burn not verified", 5)
        return score(rep)

    async def scan(self, limit: int = 10) -> list[TokenReport]:
        mints = await self.discover(limit)
        if not mints:
            return []
        try:
            pairs = await self.pairs_for(mints)
        except ProviderError:
            pairs = {}
        out = []
        for m in mints:
            try:
                out.append(await self.analyze(m, pairs.get(m)))
            except Exception as e:  # noqa: BLE001 — one bad token never aborts the scan
                log.warning("token analysis failed", extra={"data": {"mint": m, "error": str(e)[:160]}})
        return out

    def health(self) -> dict:
        return {"dexscreener": self.dex.health(), "jupiter": self.jup.health(), "solana_rpc": self.rpc.health()}
