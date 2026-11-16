import { describe, expect, it } from "vitest";
import { compact, duration, pair, pct, price, signedUsd, tone, usd } from "@/lib/format";

describe("format", () => {
  it("formats prices by magnitude", () => {
    expect(price(3857.656, 2)).toBe("3,857.66");
    expect(price(1.100045, 5)).toBe("1.10005");
    expect(price(159.4371, 3)).toBe("159.437");

    expect(price(null)).toBe("—");
    expect(price(Number.NaN)).toBe("—");
  });
  it("formats money and percentages with signs", () => {
    expect(usd(-12.5)).toBe("-$12.50");
    expect(signedUsd(3)).toBe("+$3.00");
    expect(pct(1.234)).toBe("+1.23%");
    expect(pct(-0.5, 1)).toBe("-0.5%");
    expect(compact(1_520_000)).toBe("$1.52M");
  });
  it("tones gains and losses", () => {
    expect(tone(1)).toBe("text-up");
    expect(tone(-1)).toBe("text-down");
    expect(tone(0)).toBe("text-ink-2");
  });
  it("formats durations and pairs", () => {
    expect(duration(59)).toBe("59s");
    expect(duration(3700)).toBe("1h 1m");
    expect(pair("XAUUSD")).toBe("XAU/USD");
    expect(pair("EURUSD")).toBe("EUR/USD");
  });
});
