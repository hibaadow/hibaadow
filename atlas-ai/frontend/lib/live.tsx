"use client";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export type LiveEvent = { type: string; ts?: string; data: any };
type Listener = (e: LiveEvent) => void;
type Ctx = { connected: boolean; quotes: Record<string, { bid: number; ask: number; ts: number }>; subscribe: (fn: Listener) => () => void };

const LiveCtx = createContext<Ctx>({ connected: false, quotes: {}, subscribe: () => () => {} });

export function LiveProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [quotes, setQuotes] = useState<Ctx["quotes"]>({});
  const listeners = useRef(new Set<Listener>());

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let retry = 1000;
    let ping: ReturnType<typeof setInterval> | undefined;
    const url = process.env.NEXT_PUBLIC_WS_URL || `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`;
    const connect = () => {
      if (stop) return;
      ws = new WebSocket(url);
      ws.onopen = () => { setConnected(true); retry = 1000; ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000); };
      ws.onmessage = (m) => {
        let ev: LiveEvent;
        try { ev = JSON.parse(m.data); } catch { return; }
        if (ev.type === "quotes") setQuotes(ev.data);
        listeners.current.forEach((fn) => fn(ev));
      };
      ws.onclose = () => { setConnected(false); clearInterval(ping); if (!stop) setTimeout(connect, (retry = Math.min(retry * 2, 15000))); };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => { stop = true; clearInterval(ping); ws?.close(); };
  }, []);

  const subscribe = (fn: Listener) => { listeners.current.add(fn); return () => { listeners.current.delete(fn); }; };
  return <LiveCtx.Provider value={{ connected, quotes, subscribe }}>{children}</LiveCtx.Provider>;
}

export const useLive = () => useContext(LiveCtx);

/** Poll an endpoint, refetching on matching live events. */
import { api } from "./api";
export function usePoll<T>(path: string | null, intervalMs = 10000, refreshOn: string[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { subscribe } = useLive();
  const [tick, setTick] = useState(0);
  const refresh = () => setTick((t) => t + 1);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const load = () => api<T>(path).then((d) => { if (alive) { setData(d); setError(null); } }).catch((e) => alive && setError(String(e.message || e)));
    load();
    const id = setInterval(load, intervalMs);
    const unsub = refreshOn.length ? subscribe((e) => { if (refreshOn.includes(e.type)) load(); }) : () => {};
    return () => { alive = false; clearInterval(id); unsub(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, intervalMs, tick]);
  return { data, error, refresh, setData };
}
