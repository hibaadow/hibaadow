"use client";
import { useEffect, useRef } from "react";
import {
  AreaSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart,
  type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";

const C = { bg: "#0e131a", grid: "#151c27", text: "#7f8a9b", up: "#16c784", down: "#ef4559", accent: "#4f8cff", warn: "#f0a538" };

function base(el: HTMLElement): IChartApi {
  return createChart(el, {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: C.bg }, textColor: C.text, fontSize: 11, attributionLogo: false,
      fontFamily: "JetBrains Mono, SF Mono, ui-monospace, Menlo, monospace" },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
    rightPriceScale: { borderColor: "#1b2330" },
    timeScale: { borderColor: "#1b2330", timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
  });
}

function precisionFor(p: number) {
  const a = Math.abs(p);
  const precision = a >= 1000 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 6 : 9;
  return { type: "price" as const, precision, minMove: Math.pow(10, -precision) };
}

export type CandleData = { t: number; o: number; h: number; l: number; c: number; v: number };
export type Level = { price: number; label: string; color: "up" | "down" | "accent" | "warn" };

export function CandleChart({ candles, overlays, levels, live, height = 460, digits }: {
  candles: CandleData[]; overlays: Record<string, (number | null)[]>; levels: Level[]; live?: number | null; height?: number; digits?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ candle?: ISeriesApi<"Candlestick">; vol?: ISeriesApi<"Histogram">; lines: Record<string, ISeriesApi<"Line">>; rsi?: ISeriesApi<"Line">; priceLines: IPriceLine[] }>({ lines: {}, priceLines: [] });

  useEffect(() => {
    if (!el.current) return;
    const ch = base(el.current);
    chart.current = ch;
    const s = series.current;
    s.candle = ch.addSeries(CandlestickSeries, { upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down });
    s.vol = ch.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    s.vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const colors: Record<string, string> = { ema9: "#f0a538", ema21: "#4f8cff", ema50: "#a970ff", ema200: "#e8e8e8", vwap: "#2dd4bf" };
    for (const k of Object.keys(colors)) {
      s.lines[k] = ch.addSeries(LineSeries, { color: colors[k], lineWidth: k === "ema200" ? 2 : 1, lastValueVisible: false, priceLineVisible: false,
        crosshairMarkerVisible: false, lineStyle: k === "vwap" ? LineStyle.Dashed : LineStyle.Solid, title: k.toUpperCase() });
    }
    s.rsi = ch.addSeries(LineSeries, { color: "#c084fc", lineWidth: 1, priceLineVisible: false, title: "RSI 14" }, 1);
    s.rsi.createPriceLine({ price: 70, color: "#3a4352", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    s.rsi.createPriceLine({ price: 30, color: "#3a4352", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    const panes = ch.panes();
    if (panes[1]) panes[1].setHeight(90);
    return () => { ch.remove(); chart.current = null; series.current = { lines: {}, priceLines: [] }; };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!s.candle || !candles.length) return;
    const fmt = digits != null ? { type: "price" as const, precision: digits, minMove: Math.pow(10, -digits) } : precisionFor(candles[candles.length - 1].c);
    s.candle.applyOptions({ priceFormat: fmt });
    s.candle.setData(candles.map((x) => ({ time: x.t as UTCTimestamp, open: x.o, high: x.h, low: x.l, close: x.c })));
    s.vol!.setData(candles.map((x) => ({ time: x.t as UTCTimestamp, value: x.v, color: x.c >= x.o ? "rgba(22,199,132,.28)" : "rgba(239,69,89,.28)" })));
    for (const [k, line] of Object.entries(s.lines)) {
      line.applyOptions({ priceFormat: fmt });
      const vals = overlays[k] || [];
      line.setData(candles.flatMap((x, i) => (vals[i] == null ? [] : [{ time: x.t as UTCTimestamp, value: vals[i] as number }])));
    }
    const r = overlays.rsi || [];
    s.rsi!.setData(candles.flatMap((x, i) => (r[i] == null ? [] : [{ time: x.t as UTCTimestamp, value: r[i] as number }])));
  }, [candles, overlays, digits]);

  useEffect(() => {
    const s = series.current;
    if (!s.candle) return;
    s.priceLines.forEach((pl) => s.candle!.removePriceLine(pl));
    s.priceLines = levels.map((l) => s.candle!.createPriceLine({ price: l.price, color: C[l.color], lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: l.label }));
  }, [levels]);

  useEffect(() => {
    const s = series.current;
    if (!s.candle || !live || !candles.length) return;
    const last = candles[candles.length - 1];
    s.candle.update({ time: last.t as UTCTimestamp, open: last.o, high: Math.max(last.h, live), low: Math.min(last.l, live), close: live });
  }, [live, candles]);

  return <div ref={el} style={{ height }} className="w-full" />;
}

export function LineChart({ points, height = 240, color = "accent", area = true, percent = false }: {
  points: { t: number; v: number }[]; height?: number; color?: "accent" | "up" | "down"; area?: boolean; percent?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const s = useRef<ISeriesApi<"Area"> | ISeriesApi<"Line"> | null>(null);
  const ch = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!el.current) return;
    const chart = base(el.current);
    ch.current = chart;
    const col = C[color];
    const fmt = percent ? { type: "custom" as const, formatter: (x: number) => x.toFixed(2) + "%" } : { type: "price" as const, precision: 2, minMove: 0.01 };
    s.current = area
      ? chart.addSeries(AreaSeries, { lineColor: col, topColor: col + "33", bottomColor: col + "00", lineWidth: 2, priceFormat: fmt })
      : chart.addSeries(LineSeries, { color: col, lineWidth: 2, priceFormat: fmt });
    return () => { chart.remove(); };
  }, [color, area, percent]);
  useEffect(() => {
    if (!s.current) return;
    const seen = new Set<number>();
    const data = points.filter((p) => (seen.has(p.t) ? false : (seen.add(p.t), true))).sort((a, b) => a.t - b.t);
    s.current.setData(data.map((p) => ({ time: p.t as UTCTimestamp, value: p.v })));
    ch.current?.timeScale().fitContent();
  }, [points]);
  return <div ref={el} style={{ height }} className="w-full" />;
}

export function Bars({ values, labels, height = 180 }: { values: number[]; labels?: string[]; height?: number }) {
  const max = Math.max(1e-9, ...values.map(Math.abs));
  return (
    <div className="flex items-end gap-[3px] w-full" style={{ height }}>
      {values.map((v, i) => (
        <div key={i} className="flex-1 flex flex-col justify-end items-center min-w-0 h-full" title={`${labels?.[i] ?? i}: ${v}`}>
          <div className={`w-full rounded-t-[2px] ${v >= 0 ? "bg-up/70" : "bg-down/70"}`} style={{ height: `${(Math.abs(v) / max) * 100}%`, minHeight: v ? 2 : 0 }} />
          {labels && <div className="text-[9.5px] text-mute mt-1 truncate w-full text-center num">{labels[i]}</div>}
        </div>
      ))}
    </div>
  );
}
