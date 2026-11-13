"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Sentiment, type TopicsOverview, type TopicTerm } from "@/lib/api";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { layoutCloud } from "@/lib/wordcloud";
import { useI18n } from "@/lib/i18n";

const pct = (n: number, d: number) => (d ? Math.round((n / d) * 100) : 0);

/** Tono de un término: rojo si la mayoría de sus menciones son negativas, verde si son positivas; si no, azul. */
function tone(term: TopicTerm): "negative" | "positive" | "mixed" {
  if (term.negative * 2 > term.count) return "negative";
  if (term.positive * 2 > term.count) return "positive";
  return "mixed";
}

let canvas: HTMLCanvasElement | null = null;
function measurer(family: string) {
  canvas ??= document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  return (text: string, size: number) => {
    if (!ctx) return text.length * size * 0.6;
    ctx.font = `600 ${size}px ${family}`;
    return ctx.measureText(text).width;
  };
}

/** Nube con los temas más mencionados sobre un objetivo: palabras, frases y hashtags de sus menciones. */
export function TopicCloudCard({ targetId, targetName, refreshKey }: {
  targetId: string;
  targetName: string;
  /** Cambia cuando llegan menciones nuevas, para volver a pedir los datos. */
  refreshKey?: number;
}) {
  const phone = useMediaQuery(PHONE);
  const { t, nf: fmt } = useI18n();
  const [days, setDays] = useState(30);
  const [sentiment, setSentiment] = useState<Sentiment | "">("");
  const [data, setData] = useState<TopicsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  // Las menciones en vivo piden datos nuevos, pero a lo más una vez por minuto.
  const lastLive = useRef(0);
  const [liveTick, setLiveTick] = useState(0);
  useEffect(() => {
    if (refreshKey === undefined || Date.now() - lastLive.current < 60_000) return;
    lastLive.current = Date.now();
    setLiveTick((n) => n + 1);
  }, [refreshKey]);

  useEffect(() => {
    let stale = false;
    api.topics(targetId, days, sentiment)
      .then((d) => { if (!stale) { setData(d); setError(null); } })
      .catch((e: Error) => { if (!stale) setError(e.message); });
    return () => { stale = true; };
  }, [targetId, days, sentiment, liveTick]);

  useEffect(() => setPicked(null), [targetId, days, sentiment]);

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  const height = phone ? 300 : 380;
  const terms = useMemo(() => (data?.terms ?? []).slice(0, phone ? 45 : 80), [data, phone]);
  const placed = useMemo(() => {
    if (!width || !terms.length || !box.current) return [];
    const family = getComputedStyle(box.current).fontFamily || "system-ui, sans-serif";
    return layoutCloud(
      terms.map((x) => ({ key: x.term, text: x.term, weight: x.count })),
      width, height, { minSize: phone ? 11 : 12, maxSize: phone ? 32 : 48, measure: measurer(family) },
    );
  }, [terms, width, height, phone]);
  const byTerm = useMemo(() => new Map(terms.map((x) => [x.term, x])), [terms]);
  const selected = picked ? byTerm.get(picked) : undefined;

  const describe = (x: TopicTerm) =>
    `${x.term}: ${t("{n} menciones", { n: x.count })} · ${t("{pct} negativas", { pct: `${pct(x.negative, x.count)}%` })} · ${t("{pct} positivas", { pct: `${pct(x.positive, x.count)}%` })}`;

  return (
    <section className="card span-12 topics-card">
      <div className="card-head">
        <h2>{t("¿De qué se habla sobre {name}?", { name: targetName })}</h2>
        <div className="geo-controls">
          <select aria-label={t("Periodo")} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>{t("Últimas 24 h")}</option>
            <option value={7}>{t("Últimos 7 días")}</option>
            <option value={30}>{t("Últimos 30 días")}</option>
            <option value={90}>{t("Últimos 90 días")}</option>
            <option value={365}>{t("Último año")}</option>
          </select>
          <select aria-label={t("Sentimiento")} value={sentiment} onChange={(e) => setSentiment(e.target.value as Sentiment | "")}>
            <option value="">{t("Todas las menciones")}</option>
            <option value="negative">{t("Solo negativas")}</option>
            <option value="neutral">{t("Solo neutras")}</option>
            <option value="positive">{t("Solo positivas")}</option>
          </select>
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="geo-body">
        <div className="topics-cloud" ref={box} style={{ height }}>
          {!data ? <div className="empty">{t("Cargando…")}</div>
            : !terms.length ? <div className="empty">{t("Todavía no hay suficientes menciones en este periodo para ver temas.")}</div>
            : (
              <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
                aria-label={t("Nube de temas: {terms}", { terms: terms.slice(0, 10).map((x) => x.term).join(", ") })}>
                {placed.map((p) => {
                  const term = byTerm.get(p.key)!;
                  return (
                    <text key={p.key} x={p.x} y={p.y} fontSize={p.size} textAnchor="middle" dominantBaseline="central"
                      className={`word ${tone(term)} ${term.kind} ${picked === p.key ? "picked" : ""} ${picked && picked !== p.key ? "dim" : ""}`}
                      tabIndex={0} role="button" aria-pressed={picked === p.key}
                      onClick={() => setPicked(picked === p.key ? null : p.key)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(picked === p.key ? null : p.key); } }}>
                      <title>{describe(term)}</title>
                      {p.text}
                    </text>
                  );
                })}
              </svg>
            )}
        </div>

        <aside className="geo-side">
          {data && (
            <>
              <p className="topics-detail" aria-live="polite">
                {selected ? (
                  <><b>{selected.term}</b> · {t("en {n} menciones", { n: selected.count })} · <span style={{ color: "var(--neg)" }}>{t("{pct} negativas", { pct: `${pct(selected.negative, selected.count)}%` })}</span> · <span style={{ color: "var(--pos)" }}>{t("{pct} positivas", { pct: `${pct(selected.positive, selected.count)}%` })}</span></>
                ) : (
                  <span className="muted">{t("Toca una palabra para ver cuántas menciones la usan y su tono.")}</span>
                )}
              </p>
              {terms.length > 0 && (
                <div className="scroll-x"><table>
                  <thead><tr><th>{t("Tema")}</th><th className="num">{t("Menciones")}</th><th className="num">{t("Negativas")}</th></tr></thead>
                  <tbody>
                    {terms.slice(0, 10).map((x) => (
                      <tr key={x.term} className={picked === x.term ? "picked" : undefined} onClick={() => setPicked(picked === x.term ? null : x.term)}>
                        <td><span className={`dot ${tone(x)}`} />{x.term}</td>
                        <td className="num">{fmt.format(x.count)}</td>
                        <td className="num" style={{ color: x.negative ? "var(--neg)" : undefined }}>{pct(x.negative, x.count)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              <div className="topics-legend muted">
                <span><span className="dot negative" />{t("Mayoría negativas")}</span>
                <span><span className="dot positive" />{t("Mayoría positivas")}</span>
                <span><span className="dot mixed" />{t("Mixto o neutro")}</span>
              </div>
              <p className="muted hint">
                {data.analyzed < data.total
                  ? t("Temas de las {n} menciones más recientes de {total}.", { n: data.analyzed, total: data.total })
                  : t("Temas de {n} menciones.", { n: data.total })}
                {" "}{t("El tamaño es en cuántas menciones aparece cada palabra, frase o hashtag. No se cuentan el nombre del objetivo, sus alias ni palabras comunes en español, inglés y francés.")}
              </p>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
