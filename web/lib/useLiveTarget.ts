"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL, api, type Alert, type Breakdown, type Mention, type Risk, type Screening } from "./api";

export type LiveStatus = "connecting" | "live" | "offline";

/** Carga el historial de un objetivo y lo mantiene al día por WebSocket. */
export function useLiveTarget(targetId: string | null, onAlert?: (alert: Alert) => void) {
  const alertHandler = useRef(onAlert);
  alertHandler.current = onAlert;
  const [risk, setRisk] = useState<Risk[]>([]);
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [screening, setScreening] = useState<Screening | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    if (!targetId) return;
    let cancelled = false;

    const refreshBreakdown = () => api.breakdown(targetId).then((b) => !cancelled && setBreakdown(b)).catch(() => {});
    Promise.all([api.risk(targetId), api.mentions(targetId), api.alerts(targetId)])
      .then(([r, m, a]) => {
        if (cancelled) return;
        setRisk(r);
        setMentions(m);
        setAlerts(a);
      })
      .catch(() => setStatus("offline"));
    refreshBreakdown();
    setScreening(null);
    const refreshScreening = () => api.screening(targetId).then((s) => !cancelled && setScreening(s)).catch(() => {});
    refreshScreening();

    // Canal en vivo: /ws/targets/{id} manda {event, data}. Se reconecta con espera creciente.
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let attempt = 0;

    const handle = (event: string, data: unknown) => {
      if (event === "riskUpdated") {
        setRisk((prev) => [...prev.slice(-2000), data as Risk]);
        refreshBreakdown();
      } else if (event === "mentionsAdded") {
        const added = data as Mention[];
        setMentions((prev) => [...added, ...prev.filter((p) => !added.some((a) => a.id === p.id))].slice(0, 100));
      } else if (event === "mentionUpdated") {
        const updated = data as Mention;
        setMentions((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      } else if (event === "screeningUpdated") {
        setScreening(data as Screening);
      } else if (event === "alertRaised") {
        const alert = data as Alert;
        setAlerts((prev) => [{ ...alert, at: alert.at ?? new Date().toISOString() }, ...prev].slice(0, 50));
        alertHandler.current?.(alert);
      }
    };

    const connect = () => {
      if (cancelled) return;
      setStatus("connecting");
      socket = new WebSocket(`${WS_URL}/ws/targets/${targetId}`);
      socket.onopen = () => {
        attempt = 0;
        setStatus("live");
        ping = setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send("ping"), 25_000);
      };
      socket.onmessage = (msg) => {
        try {
          const { event, data } = JSON.parse(msg.data as string) as { event: string; data: unknown };
          handle(event, data);
        } catch {
          /* mensaje no reconocido */
        }
      };
      socket.onclose = () => {
        clearInterval(ping);
        if (cancelled) return;
        setStatus("offline");
        retry = setTimeout(connect, Math.min(30_000, 1_000 * 2 ** attempt++));
      };
    };
    connect();

    return () => {
      cancelled = true;
      clearTimeout(retry);
      clearInterval(ping);
      socket?.close();
    };
  }, [targetId]);

  return {
    risk, mentions, breakdown, alerts, status, latest: risk.at(-1) ?? null, screening,
    refreshScreening: () => targetId && api.screening(targetId).then(setScreening).catch(() => {}),
    replaceMention: (m: Mention) => setMentions((prev) => prev.map((p) => (p.id === m.id ? m : p))),
  };
}
