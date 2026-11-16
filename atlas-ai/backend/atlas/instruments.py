"""Tradable universe: XAU/USD and selected FX pairs ONLY.

ATLAS AI is a gold and forex day-trading agent. Any symbol not defined here is
rejected everywhere (config validation, API, strategies, brokers).

Contract conventions (standard retail CFD/spot FX — confirm against your broker's
symbol specification; MT5 values are read from the terminal when connected):
* FX: 1 lot = 100,000 units of the base currency; pip = 0.0001 (0.01 for JPY quotes).
* XAU/USD: 1 lot = 100 troy ounces; pip = 0.10 USD (point = 0.01).
* Pip value per lot (in quote currency) = pip_size × contract_size, converted to the
  USD account currency with live rates.
"""
from __future__ import annotations

from dataclasses import dataclass

ACCOUNT_CURRENCY = "USD"


@dataclass(frozen=True)
class Instrument:
    symbol: str  # canonical, e.g. EURUSD / XAUUSD
    display: str
    asset_class: str  # gold | forex
    base: str
    quote: str
    pip_size: float
    digits: int
    contract_size: float
    margin_rate: float  # e.g. 0.0333 = 30:1 leverage
    max_spread_pips: float  # default spread ceiling
    slippage_pips: float  # modelled slippage for market orders in normal conditions
    category: str = "major"  # major | minor | metal
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0

    @property
    def oanda(self) -> str:
        return f"{self.base}_{self.quote}"

    @property
    def public_feed(self) -> str:
        return f"{self.base}/{self.quote}"

    @property
    def pip_value_quote(self) -> float:
        """Value of one pip for 1.0 lot, in the quote currency."""
        return self.pip_size * self.contract_size

    @property
    def currencies(self) -> tuple[str, ...]:
        return (self.base, self.quote) if self.asset_class == "forex" else ("USD",)

    def to_pips(self, price_distance: float) -> float:
        return price_distance / self.pip_size

    def round_price(self, p: float) -> float:
        return round(p, self.digits)


def _fx(sym, cat, digits, margin, spread, slip):
    base, quote = sym[:3], sym[3:]
    pip = 0.01 if quote == "JPY" else 0.0001
    return Instrument(sym, f"{base}/{quote}", "forex", base, quote, pip, digits, 100_000.0, margin, spread, slip, cat)


INSTRUMENTS: dict[str, Instrument] = {
    "XAUUSD": Instrument("XAUUSD", "XAU/USD", "gold", "XAU", "USD", 0.10, 2, 100.0, 0.05, 8.0, 1.5, "metal",
                         min_lot=0.01, lot_step=0.01, max_lot=20.0),
    **{s: _fx(s, *rest) for s, *rest in [
        ("EURUSD", "major", 5, 1 / 30, 1.5, 0.2),
        ("GBPUSD", "major", 5, 1 / 30, 2.0, 0.3),
        ("USDJPY", "major", 3, 1 / 30, 1.8, 0.3),
        ("AUDUSD", "major", 5, 1 / 20, 2.0, 0.3),
        ("USDCAD", "major", 5, 1 / 30, 2.5, 0.3),
        ("USDCHF", "major", 5, 1 / 30, 2.5, 0.3),
        ("NZDUSD", "major", 5, 1 / 20, 2.8, 0.3),
        ("EURGBP", "minor", 5, 1 / 30, 2.2, 0.3),
        ("EURJPY", "minor", 3, 1 / 20, 2.8, 0.4),
        ("GBPJPY", "minor", 3, 1 / 20, 4.0, 0.5),
    ]},
}

GOLD = "XAUUSD"
FOREX = [s for s, i in INSTRUMENTS.items() if i.asset_class == "forex"]
DEFAULT_UNIVERSE = [GOLD, *FOREX]
# Pairs needed to convert any quote currency to USD (always quoted, even if not traded).
CONVERSION_PAIRS = {"EUR": "EURUSD", "GBP": "GBPUSD", "AUD": "AUDUSD", "NZD": "NZDUSD", "JPY": "USDJPY", "CAD": "USDCAD", "CHF": "USDCHF"}


class UnsupportedInstrument(ValueError):
    pass


def get(symbol: str) -> Instrument:
    s = normalize(symbol)
    if s not in INSTRUMENTS:
        raise UnsupportedInstrument(f"{symbol!r} is not a supported gold/forex instrument")
    return INSTRUMENTS[s]


def normalize(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("_", "").replace("-", "").strip()


def is_supported(symbol: str) -> bool:
    return normalize(symbol) in INSTRUMENTS


def to_usd_rate(currency: str, mids: dict[str, float]) -> float | None:
    """Units of USD per 1 unit of ``currency`` using live mid prices (None if unknown)."""
    if currency == "USD":
        return 1.0
    if currency == "XAU":
        return mids.get("XAUUSD")
    pair = CONVERSION_PAIRS.get(currency)
    px = mids.get(pair) if pair else None
    if not px:
        return None
    return px if pair.startswith(currency) else 1.0 / px


def pip_value_usd(inst: Instrument, mids: dict[str, float]) -> float | None:
    """USD value of one pip for 1.0 lot."""
    rate = to_usd_rate(inst.quote, mids)
    return None if rate is None else inst.pip_value_quote * rate


def notional_usd(inst: Instrument, lots: float, price: float, mids: dict[str, float]) -> float | None:
    rate = to_usd_rate(inst.quote, mids)
    return None if rate is None else lots * inst.contract_size * price * rate


def margin_usd(inst: Instrument, lots: float, price: float, mids: dict[str, float], leverage_override: float | None = None) -> float | None:
    n = notional_usd(inst, lots, price, mids)
    if n is None:
        return None
    rate = (1 / leverage_override) if leverage_override else inst.margin_rate
    return n * rate


def floor_lots(inst: Instrument, lots: float) -> float:
    """Round DOWN to the broker lot step (never round risk up)."""
    steps = int(lots / inst.lot_step + 1e-9)
    return round(min(steps * inst.lot_step, inst.max_lot), 2)
