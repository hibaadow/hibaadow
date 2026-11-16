"""Resilient HTTP client: per-provider rate limiting, retries with backoff,
429/418 Retry-After handling and response-shape validation hooks."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from ..config import get_settings
from ..logging import get_logger

log = get_logger("atlas.http")


class ProviderError(Exception):
    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()
        self.blocked_until = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class ProviderClient:
    """One instance per external provider."""

    def __init__(self, name: str, base_url: str, rate_per_sec: float = 5, burst: int = 10,
                 max_retries: int = 3, timeout: float | None = None, headers: dict | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.bucket = TokenBucket(rate_per_sec, burst)
        self.max_retries = max_retries
        self.timeout = timeout or get_settings().http_timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self.last_latency_ms: float | None = None
        self.last_error: str | None = None
        self.last_ok: float | None = None
        self.consecutive_failures = 0
        self._headers = headers or {}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": "atlas-ai/1.0", "Accept": "application/json", **self._headers},
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None, expect: str = "json") -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            await self.bucket.acquire()
            t0 = time.perf_counter()
            try:
                r = await self._http().request(method, url, params=params, json=json)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self._fail(f"network error: {type(e).__name__}")
                if attempt >= self.max_retries:
                    raise ProviderError(self.name, f"network error after retries: {type(e).__name__}") from e
                await asyncio.sleep(delay + random.random() * 0.25)
                delay *= 2
                continue
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            if r.status_code in (418, 429):
                retry_after = float(r.headers.get("Retry-After", "0") or 0) or delay * 2
                self.bucket.blocked_until = time.monotonic() + min(retry_after, 120)
                self._fail(f"rate limited ({r.status_code}), backing off {retry_after:.0f}s")
                if attempt >= self.max_retries:
                    raise ProviderError(self.name, "rate limited", r.status_code)
                continue
            if r.status_code >= 500:
                self._fail(f"server error {r.status_code}")
                if attempt >= self.max_retries:
                    raise ProviderError(self.name, f"server error {r.status_code}", r.status_code)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if r.status_code >= 400:
                self._fail(f"client error {r.status_code}")
                body = r.text[:200] if r.status_code not in (401, 403) else "unauthorized (check credentials)"
                raise ProviderError(self.name, f"HTTP {r.status_code}: {body}", r.status_code)
            ctype = r.headers.get("content-type", "")
            if expect == "text":
                self.last_ok = time.time()
                self.last_error = None
                self.consecutive_failures = 0
                return r.text[:5_000_000]
            if "json" not in ctype:
                self._fail(f"unexpected content-type {ctype!r}")
                raise ProviderError(self.name, f"unexpected content-type {ctype!r}")
            if len(r.content) > 20_000_000:
                raise ProviderError(self.name, "response too large")
            try:
                data = r.json()
            except ValueError as e:
                self._fail("invalid json")
                raise ProviderError(self.name, "invalid JSON response") from e
            self.last_ok = time.time()
            self.last_error = None
            self.consecutive_failures = 0
            return data
        raise ProviderError(self.name, "exhausted retries")

    async def get(self, path: str, **params) -> Any:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    async def get_text(self, path: str, **params) -> str:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None}, expect="text")

    async def post(self, path: str, payload: Any) -> Any:
        return await self.request("POST", path, json=payload)

    async def put(self, path: str, payload: Any) -> Any:
        return await self.request("PUT", path, json=payload)

    def _fail(self, msg: str) -> None:
        self.last_error = msg
        self.consecutive_failures += 1
        log.warning("provider request failed", extra={"data": {"provider": self.name, "error": msg}})

    def health(self) -> dict:
        if self.last_ok is None and self.last_error is None:
            status = "unknown"
        elif self.consecutive_failures >= 3:
            status = "down"
        elif self.consecutive_failures > 0:
            status = "degraded"
        else:
            status = "ok"
        return {"status": status, "latency_ms": self.last_latency_ms, "last_error": self.last_error, "last_ok": self.last_ok}
