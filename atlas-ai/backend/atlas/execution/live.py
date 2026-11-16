"""Live execution on Solana via Jupiter swap routing.

DISABLED BY DEFAULT. Live orders require ALL of:
1. ``ATLAS_LIVE_TRADING_ALLOWED=true`` in the server environment (operator gate),
2. trading config ``mode = "live"`` set by an admin,
3. ``live_confirmed = true`` (explicit acknowledgement in the UI),
4. a keypair file mounted as a secret at ``ATLAS_SOLANA_KEYPAIR_PATH`` (mode 0600). Seed phrases are never accepted,
   stored in the database, logged, or sent to any AI model.

Flow per order: Jupiter quote → price-impact / slippage guard → swap transaction build → local signing →
RPC ``simulateTransaction`` → ``sendTransaction`` → confirmation polling → balance reconciliation.
Protective stops/targets are enforced client-side by the engine (spot DEX swaps have no native stop orders),
so the worker must be running for stops to be honoured — document and monitor accordingly.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import time
from dataclasses import dataclass

from ..config import get_settings
from ..logging import get_logger
from ..marketdata.http import ProviderClient, ProviderError
from ..trading_config import TradingConfig

log = get_logger("atlas.live")

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
# Native SPL mints for symbols that can be swapped on Solana. BTC/ETH are excluded on purpose:
# their Solana representations are bridged/wrapped assets with different risk.
SOLANA_MINTS = {
    "SOL": ("So11111111111111111111111111111111111111112", 9),
    "JUP": ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", 6),
    "WIF": ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", 6),
    "BONK": ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 5),
    "JTO": ("jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", 9),
    "RAY": ("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", 6),
    "PYTH": ("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", 6),
}


class LiveTradingDisabled(Exception):
    pass


@dataclass
class LiveFill:
    signature: str
    in_amount: float
    out_amount: float
    price: float
    status: str


def preflight(cfg: TradingConfig) -> list[str]:
    """Return a list of unmet requirements (empty = armed)."""
    s = get_settings()
    problems = []
    if not s.live_trading_allowed:
        problems.append("server env ATLAS_LIVE_TRADING_ALLOWED is not true")
    if cfg.mode != "live":
        problems.append("trading mode is paper")
    if not cfg.live_confirmed:
        problems.append("live trading has not been explicitly confirmed by an admin")
    path = s.solana_keypair_path
    if not path:
        problems.append("ATLAS_SOLANA_KEYPAIR_PATH not set")
    elif not os.path.isfile(path):
        problems.append("keypair file not found")
    else:
        mode = os.stat(path).st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            problems.append("keypair file permissions too open (require 0600)")
    try:
        import solders  # noqa: F401
    except ImportError:
        problems.append("python package 'solders' not installed")
    return problems


def _load_keypair():
    from solders.keypair import Keypair

    path = get_settings().solana_keypair_path
    with open(path) as fh:  # standard solana-keygen JSON array of 64 bytes
        raw = json.load(fh)
    if not isinstance(raw, list) or len(raw) != 64:
        raise LiveTradingDisabled("keypair file must be a solana-keygen JSON array (seed phrases are not accepted)")
    return Keypair.from_bytes(bytes(raw))


class JupiterLiveExecutor:
    mode = "live"
    venue = "jupiter"

    def __init__(self, cfg: TradingConfig):
        s = get_settings()
        self.cfg = cfg
        self.jup = ProviderClient("jupiter_exec", s.jupiter_url, rate_per_sec=1, burst=2, max_retries=1)
        self.rpc = ProviderClient("solana_rpc_exec", s.solana_rpc_url, rate_per_sec=2, burst=4, max_retries=1)
        self._inflight: set[str] = set()

    def supported(self, symbol: str) -> bool:
        from ..marketdata.providers import split_symbol

        return split_symbol(symbol)[0] in SOLANA_MINTS

    async def _rpc(self, method: str, params: list):
        d = await self.rpc.post("", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in d:
            raise ProviderError("solana_rpc", str(d["error"])[:200])
        return d["result"]

    async def quote(self, input_mint: str, output_mint: str, amount_units: int) -> dict:
        q = await self.jup.get("/swap/v1/quote", inputMint=input_mint, outputMint=output_mint, amount=amount_units,
                               slippageBps=int(self.cfg.risk.max_slippage_bps), restrictIntermediateTokens="true")
        if not isinstance(q, dict) or not q.get("outAmount"):
            raise ProviderError("jupiter", f"no route: {q}")
        impact_bps = float(q.get("priceImpactPct") or 0) * 1e4
        if impact_bps > self.cfg.risk.max_slippage_bps:
            raise ProviderError("jupiter", f"price impact {impact_bps:.1f} bps exceeds limit")
        return q

    async def swap(self, client_order_id: str, input_mint: str, output_mint: str, amount_units: int, in_dec: int, out_dec: int) -> LiveFill:
        problems = preflight(self.cfg)
        if problems:
            raise LiveTradingDisabled("; ".join(problems))
        if client_order_id in self._inflight:
            raise LiveTradingDisabled(f"order {client_order_id} already in flight (duplicate prevented)")
        self._inflight.add(client_order_id)
        try:
            from solders.transaction import VersionedTransaction

            kp = _load_keypair()
            q = await self.quote(input_mint, output_mint, amount_units)
            built = await self.jup.post("/swap/v1/swap", {"quoteResponse": q, "userPublicKey": str(kp.pubkey()),
                                                         "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
                                                         "dynamicSlippage": False})
            raw = base64.b64decode(built["swapTransaction"])
            unsigned = VersionedTransaction.from_bytes(raw)
            signed = VersionedTransaction(unsigned.message, [kp])
            b64 = base64.b64encode(bytes(signed)).decode()
            sim = await self._rpc("simulateTransaction", [b64, {"encoding": "base64", "commitment": "processed"}])
            if (sim or {}).get("value", {}).get("err"):
                raise ProviderError("solana_rpc", f"simulation failed: {sim['value']['err']}")
            sig = await self._rpc("sendTransaction", [b64, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}])
            status = await self._confirm(sig, built.get("lastValidBlockHeight"))
            in_amt = int(q["inAmount"]) / 10 ** in_dec
            out_amt = int(q["outAmount"]) / 10 ** out_dec
            # NOTE: quoted amounts; reconcile() replaces with on-chain balance deltas
            return LiveFill(sig, in_amt, out_amt, in_amt / out_amt if out_amt else 0, status)
        finally:
            self._inflight.discard(client_order_id)

    async def _confirm(self, sig: str, last_valid_height: int | None, timeout: float = 75) -> str:
        t0 = time.time()
        while time.time() - t0 < timeout:
            res = await self._rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])
            st = (res or {}).get("value", [None])[0]
            if st:
                if st.get("err"):
                    raise ProviderError("solana_rpc", f"transaction failed on-chain: {st['err']}")
                if st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return st["confirmationStatus"]
            if last_valid_height:
                h = await self._rpc("getBlockHeight", [])
                if h > last_valid_height:
                    raise ProviderError("solana_rpc", "blockhash expired before confirmation")
            await asyncio.sleep(2)
        raise ProviderError("solana_rpc", "confirmation timed out — reconcile before retrying")

    async def token_balance(self, owner: str, mint: str) -> float:
        res = await self._rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
        total = 0.0
        for acc in (res or {}).get("value", []):
            total += float(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
        return total

    async def close(self):
        await self.jup.close()
        await self.rpc.close()
