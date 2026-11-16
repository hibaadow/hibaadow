"""Technical indicators (pure numpy, causal — value at index i only uses data <= i).

Every function returns an array the same length as its input with ``nan``
where the indicator is not yet defined (warm-up period). Nothing here peeks at
future bars, which is what keeps the backtester free of look-ahead bias.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

Arr = np.ndarray


def _recursive(x: Arr, alpha: float, seed: float) -> Arr:
    """y[i] = alpha*x[i] + (1-alpha)*y[i-1], y[-1] = seed  (vectorised IIR filter)."""
    y, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], x, zi=[(1.0 - alpha) * seed])
    return y


def _f(x) -> Arr:
    return np.asarray(x, dtype=float)


def sma(x, n: int) -> Arr:
    x = _f(x)
    out = np.full_like(x, np.nan)
    if n <= 0 or len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1 :] = (c[n:] - c[:-n]) / n
    return out


def ema(x, n: int) -> Arr:
    """EMA seeded with the SMA of the first ``n`` values (standard convention)."""
    x = _f(x)
    out = np.full_like(x, np.nan)
    if n <= 0 or len(x) < n:
        return out
    k = 2.0 / (n + 1)
    out[n - 1] = x[:n].mean()
    if len(x) > n:
        out[n:] = _recursive(x[n:], k, out[n - 1])
    return out


def _wilder(x: Arr, n: int) -> Arr:
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    if len(x) > n:
        out[n:] = _recursive(np.nan_to_num(x[n:]), 1.0 / n, out[n - 1])
    return out


def rsi(close, n: int = 14) -> Arr:
    c = _f(close)
    out = np.full_like(c, np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = _wilder(gain, n)
    al = _wilder(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        r = 100 - 100 / (1 + rs)
    r = np.where((al == 0) & (ag > 0), 100.0, r)
    r = np.where((al == 0) & (ag == 0), 50.0, r)
    out[1:] = r
    return out


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Arr, Arr, Arr]:
    c = _f(close)
    line = ema(c, fast) - ema(c, slow)
    sig = np.full_like(c, np.nan)
    valid = ~np.isnan(line)
    if valid.sum() >= signal:
        start = np.argmax(valid)
        sig[start:] = ema(line[start:], signal)
    return line, sig, line - sig


def true_range(high, low, close) -> Arr:
    h, l, c = _f(high), _f(low), _f(close)
    prev = np.roll(c, 1)
    prev[0] = c[0]
    return np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))


def atr(high, low, close, n: int = 14) -> Arr:
    tr = true_range(high, low, close)
    return _wilder(tr, n)


def rolling_std(x, n: int) -> Arr:
    x = _f(x)
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1 :] = win.std(axis=1, ddof=0)
    return out


def rolling_max(x, n: int) -> Arr:
    x = _f(x)
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    out[n - 1 :] = np.lib.stride_tricks.sliding_window_view(x, n).max(axis=1)
    return out


def rolling_min(x, n: int) -> Arr:
    x = _f(x)
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    out[n - 1 :] = np.lib.stride_tricks.sliding_window_view(x, n).min(axis=1)
    return out


def relative_volume(volume, n: int = 20) -> Arr:
    """Current bar volume divided by the mean of the *previous* n bars."""
    v = _f(volume)
    out = np.full_like(v, np.nan)
    if len(v) <= n:
        return out
    base = sma(v, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[n:] = v[n:] / base[n - 1 : -1]
    return out


def roc(x, n: int) -> Arr:
    x = _f(x)
    out = np.full_like(x, np.nan)
    if len(x) <= n:
        return out
    out[n:] = (x[n:] / x[:-n] - 1.0) * 100.0
    return out


def vwap(high, low, close, volume, open_time_ms, anchor_ms: int = 86_400_000) -> tuple[Arr, Arr]:
    """Session-anchored VWAP (default: UTC day) and volume-weighted std deviation."""
    h, l, c, v = _f(high), _f(low), _f(close), _f(volume)
    t = np.asarray(open_time_ms, dtype=np.int64)
    tp = (h + l + c) / 3.0
    session = t // anchor_ms
    # cumulative sums reset at each session boundary
    starts = np.r_[True, session[1:] != session[:-1]]
    gid = np.cumsum(starts) - 1

    def seg_cumsum(a):
        cs = np.cumsum(a)
        base = np.r_[0.0, cs][np.flatnonzero(starts)]
        return cs - base[gid]

    cv = seg_cumsum(v)
    cpv = seg_cumsum(tp * v)
    cpv2 = seg_cumsum(tp * tp * v)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(cv > 0, cpv / cv, np.nan)
        dev = np.where(cv > 0, np.sqrt(np.maximum(cpv2 / cv - out * out, 0.0)), np.nan)
    return out, dev


def adx(high, low, close, n: int = 14) -> Arr:
    h, l = _f(high), _f(low)
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = _wilder(true_range(high, low, close), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * _wilder(plus_dm, n) / tr
        mdi = 100 * _wilder(minus_dm, n) / tr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.nan_to_num(dx, nan=0.0)
    out = np.full_like(h, np.nan)
    if len(h) >= 2 * n:
        out[2 * n - 2 :] = _wilder(dx[n - 1 :], n)[n - 1 :]
    return out


def pivots(high, low, left: int = 3, right: int = 3) -> tuple[list[int], list[int]]:
    """Confirmed swing highs/lows. A pivot at i is only known at bar i+right."""
    h, l = _f(high), _f(low)
    ph, pl = [], []
    for i in range(left, len(h) - right):
        if h[i] == h[i - left : i + right + 1].max() and h[i] > h[i - left : i].max():
            ph.append(i)
        if l[i] == l[i - left : i + right + 1].min() and l[i] < l[i - left : i].min():
            pl.append(i)
    return ph, pl


def support_resistance(high, low, close, lookback: int = 120, tolerance_pct: float = 0.35) -> dict:
    """Cluster confirmed pivots into horizontal levels and return nearest levels."""
    h, l, c = _f(high)[-lookback:], _f(low)[-lookback:], _f(close)[-lookback:]
    if len(c) < 10:
        return {"support": None, "resistance": None, "levels": []}
    ph, pl = pivots(h, l)
    raw = sorted([h[i] for i in ph] + [l[i] for i in pl])
    levels: list[list[float]] = []
    for p in raw:
        if levels and abs(p / np.mean(levels[-1]) - 1) * 100 <= tolerance_pct:
            levels[-1].append(p)
        else:
            levels.append([p])
    lv = [{"price": float(np.mean(g)), "touches": len(g)} for g in levels]
    price = c[-1]
    sup = [x for x in lv if x["price"] < price]
    res = [x for x in lv if x["price"] > price]
    return {
        "support": max(sup, key=lambda x: x["price"]) if sup else None,
        "resistance": min(res, key=lambda x: x["price"]) if res else None,
        "levels": lv,
    }


def last(x) -> float:
    """Last finite value (nan if none)."""
    a = _f(x)
    if a.size == 0:
        return float("nan")
    return float(a[-1])
