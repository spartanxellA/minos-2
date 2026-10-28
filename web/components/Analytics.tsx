"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useState } from "react";
import {
  api, KIND_LABEL, SOURCE_LABEL, type Granularity, type MentionsOverview, type OverviewFilters, type TargetKind,
} from "@/lib/api";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { EChart } from "./EChart";

const SENT = [
  { key: "positive", label: "Positivo", color: "#2e7d32" },
  { key: "neutral", label: "Neutro", color: "#8a94a0" },
  { key: "negative", label: "Negativo", color: "#d32f2f" },
] as const;
// Sin rojo ni verde, que ya significan sentimiento y nivel de riesgo.
export const KIND_COLOR: Record<TargetKind, string> = {
  Person: "#1668b7", Company: "#e07b00", Institution: "#2a9d8f", GovernmentArea: "#8e5bd0", Country: "#c2185b",
};
const SERIES = ["#1668b7", "#e07b00", "#2a9d8f", "#8e5bd0", "#c2185b", "#6d8f00", "#0097a7", "#a1662f", "#5c6bc0", "#7b8794"];
const KINDS = Object.keys(KIND_LABEL) as TargetKind[];
const MEDIA_SOURCES = ["rss", "x", "youtube", "bluesky", "reddit", "facebook", "instagram"];
const fmt = new Intl.NumberFormat("es-MX");

function periodLabel(p: string, long = false) {
  if (p.length === 4) return p;
  const [y, m] = p.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("es-MX", { month: long ? "long" : "short", year: long ? "numeric" : "2-digit" });
}

function monthsAgo(n: number) {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - (n - 1));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const riskBands = {
  silent: true, itemStyle: { opacity: 0.06 }, data: [
    [{ yAxis: 0, itemStyle: { color: "#2e7d32" } }, { yAxis: 25 }],
    [{ yAxis: 25, itemStyle: { color: "#c9a800" } }, { yAxis: 50 }],
    [{ yAxis: 50, itemStyle: { color: "#d32f2f" } }, { yAxis: 100 }],
  ],
} as const;

/** Análisis general de todos los sujetos monitoreados: quién se menciona más, por tipo y cómo cambia por mes o año. */
export function Analytics({ onOpenTarget }: { onOpenTarget: (id: string) => void }) {
  const phone = useMediaQuery(PHONE);
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [months, setMonths] = useState(12);
  const [kind, setKind] = useState<TargetKind | "">("");
  const [source, setSource] = useState("");
  const [top, setTop] = useState(10);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [riskBy, setRiskBy] = useState<"target" | "kind">("target");
  const [data, setData] = useState<MentionsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const filters: OverviewFilters = {
      granularity, kind, source, top, includeInactive, since: granularity === "month" ? monthsAgo(months) : undefined,
    };
    let stale = false;
    setLoading(true);
    api.mentionsOverview(filters)
      .then((d) => { if (!stale) { setData(d); setError(null); } })
      .catch((err) => { if (!stale) setError((err as Error).message); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [granularity, months, kind, source, top, includeInactive]);

  const ranked = useMemo(() => (data?.ranking ?? []).filter((s) => s.mentions > 0).slice(0, top), [data, top]);
  const periods = data?.periods ?? [];
  const xPeriods = {
    type: "category" as const, data: periods.map((p) => periodLabel(p)),
    axisLabel: { hideOverlap: true }, axisTick: { alignWithLabel: true },
  };
  const grid = { left: phone ? 36 : 48, right: phone ? 8 : 16, top: 36, bottom: 28 };
  const legend = { top: 0, type: "scroll" as const };

  const rankingChart: EChartsOption = useMemo(() => ({
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    legend: { top: 0 },
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: {
      type: "category", inverse: true, data: ranked.map((s) => s.name),
      axisLabel: { width: phone ? 110 : 180, overflow: "truncate" },
    },
    series: SENT.map((s) => ({
      name: s.label, type: "bar", stack: "m", color: s.color, barMaxWidth: 22,
      data: ranked.map((r) => r[s.key]),
    })),
  }), [ranked, phone]);

  const kindChart: EChartsOption = useMemo(() => {
    const rows = data?.byKind ?? [];
    return {
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        trigger: "item", confine: true,
        formatter: (p: any) => {
          const r = rows[p.dataIndex];
          return `${KIND_LABEL[r.kind]}<br/>${fmt.format(r.mentions)} menciones · ${fmt.format(r.negative)} negativas<br/>${r.targets} sujeto(s)`;
        },
      },
      xAxis: { type: "value", minInterval: 1 },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => KIND_LABEL[r.kind]) },
      series: [{
        type: "bar", barMaxWidth: 22, label: { show: true, position: "right", formatter: (p: any) => fmt.format(p.value) },
        data: rows.map((r) => ({ value: r.mentions, itemStyle: { color: KIND_COLOR[r.kind] } })),
      }],
    };
  }, [data]);

  const kindHistory: EChartsOption = useMemo(() => {
    const rows = data?.mentionsByKind ?? [];
    const kinds = KINDS.filter((k) => rows.some((r) => r.kind === k));
    return {
      grid, legend, xAxis: xPeriods, yAxis: { type: "value", minInterval: 1 },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
      series: kinds.map((k) => ({
        name: KIND_LABEL[k], type: "bar", stack: "k", color: KIND_COLOR[k], barMaxWidth: 36,
        data: periods.map((p) => rows.find((r) => r.kind === k && r.period === p)?.count ?? 0),
      })),
    };
  }, [data, phone]);

  const targetHistory: EChartsOption = useMemo(() => {
    const rows = data?.mentionsByTarget ?? [];
    return {
      grid, legend, xAxis: xPeriods, yAxis: { type: "value", minInterval: 1 },
      tooltip: { trigger: "axis", confine: true, order: "valueDesc" },
      series: ranked.map((s, i) => ({
        name: s.name, type: "line", color: SERIES[i % SERIES.length], symbolSize: 6, showSymbol: periods.length < 30,
        data: periods.map((p) => rows.find((r) => r.targetId === s.targetId && r.period === p)?.count ?? 0),
      })),
    };
  }, [data, ranked, phone]);

  const riskHistory: EChartsOption = useMemo(() => {
    const value = (v: number | undefined) => (v === undefined ? null : v);
    const series = riskBy === "kind"
      ? KINDS.filter((k) => data?.riskByKind.some((r) => r.kind === k)).map((k) => ({
        name: KIND_LABEL[k], color: KIND_COLOR[k],
        data: periods.map((p) => value(data?.riskByKind.find((r) => r.kind === k && r.period === p)?.avg)),
      }))
      : ranked.map((s, i) => ({
        name: s.name, color: SERIES[i % SERIES.length],
        data: periods.map((p) => value(data?.riskByTarget.find((r) => r.targetId === s.targetId && r.period === p)?.avg)),
      }));
    return {
      grid, legend, xAxis: xPeriods, yAxis: { type: "value", min: 0, max: 100, interval: 25 },
      tooltip: { trigger: "axis", confine: true, order: "valueDesc", valueFormatter: (v) => (v == null ? "sin dato" : Number(v).toFixed(1)) },
      series: series.map((s, i) => ({
        ...s, type: "line", symbolSize: 6, connectNulls: true, showSymbol: periods.length < 30,
        markArea: i === 0 ? riskBands : undefined,
      })),
    } as EChartsOption;
  }, [data, ranked, riskBy, phone]);

  const range = periods.length ? `${periodLabel(periods[0], true)} – ${periodLabel(periods[periods.length - 1], true)}` : "";
  const total = data?.byKind.reduce((n, k) => n + k.mentions, 0) ?? 0;
  const empty = <div className="empty">Sin menciones en este rango.</div>;

  return (
    <div className="analytics">
      <div className="card analytics-filters">
        <div className="seg" role="group" aria-label="Agrupar por">
          <button type="button" className={granularity === "month" ? "" : "ghost"} onClick={() => setGranularity("month")}>Por mes</button>
          <button type="button" className={granularity === "year" ? "" : "ghost"} onClick={() => setGranularity("year")}>Por año</button>
        </div>
        {granularity === "month" && (
          <label>Rango
            <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
              {[6, 12, 24, 36, 60].map((n) => <option key={n} value={n}>Últimos {n} meses</option>)}
            </select>
          </label>
        )}
        <label>Tipo de sujeto
          <select value={kind} onChange={(e) => setKind(e.target.value as TargetKind | "")}>
            <option value="">Todos</option>
            {KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
        </label>
        <label>Medio
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">Todos</option>
            {MEDIA_SOURCES.map((s) => <option key={s} value={s}>{SOURCE_LABEL[s] ?? s}</option>)}
          </select>
        </label>
        <label>Mostrar
          <select value={top} onChange={(e) => setTop(Number(e.target.value))}>
            {[5, 10, 20].map((n) => <option key={n} value={n}>Top {n}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} />
          Incluir dados de baja
        </label>
        <div className="muted summary">
          {loading ? "Cargando…" : data && <>{fmt.format(total)} menciones · {range}{data.timezone !== "UTC" ? "" : " · UTC"}</>}
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="grid">
        <section className="card span-7">
          <h2>Sujetos más mencionados</h2>
          {ranked.length ? (
            <EChart replaceSeries option={rankingChart} height={Math.max(160, ranked.length * (phone ? 30 : 28) + 48)}
              onClick={(p) => { const s = ranked[p.dataIndex]; if (s) onOpenTarget(s.targetId); }} />
          ) : empty}
          {ranked.length > 0 && <p className="muted hint">Toca una barra para abrir el tablero de ese sujeto.</p>}
        </section>

        <section className="card span-5">
          <h2>Menciones por tipo de sujeto</h2>
          {total ? <EChart replaceSeries option={kindChart} height={phone ? 200 : 240} /> : empty}
        </section>

        <section className="card span-12">
          <h2>Histórico de menciones por tipo ({granularity === "month" ? "mensual" : "anual"})</h2>
          {total ? <EChart replaceSeries option={kindHistory} height={phone ? 240 : 300} /> : empty}
        </section>

        <section className="card span-12">
          <h2>Histórico de los más mencionados ({granularity === "month" ? "mensual" : "anual"})</h2>
          {ranked.length ? <EChart replaceSeries option={targetHistory} height={phone ? 260 : 320} /> : empty}
        </section>

        <section className="card span-12">
          <div className="card-head">
            <h2>Evolución histórica del índice de riesgo ({granularity === "month" ? "promedio mensual" : "promedio anual"})</h2>
            <div className="seg small" role="group" aria-label="Agrupar índice">
              <button type="button" className={riskBy === "target" ? "" : "ghost"} onClick={() => setRiskBy("target")}>Por sujeto</button>
              <button type="button" className={riskBy === "kind" ? "" : "ghost"} onClick={() => setRiskBy("kind")}>Por tipo</button>
            </div>
          </div>
          {(riskBy === "kind" ? data?.riskByKind.length : data?.riskByTarget.length)
            ? <EChart replaceSeries option={riskHistory} height={phone ? 260 : 320} />
            : <div className="empty">Sin cálculos del índice en este rango.</div>}
        </section>

        <section className="card span-12">
          <h2>Ranking</h2>
          <div className="scroll-x"><table className="ranking">
            <thead><tr>
              <th className="num">#</th><th>Sujeto</th><th className="opt">Tipo</th><th className="num">Menciones</th>
              <th className="num">Negativas</th><th className="num opt">Acusaciones graves</th><th className="num">Índice</th>
            </tr></thead>
            <tbody>
              {(data?.ranking ?? []).map((s, i) => (
                <tr key={s.targetId}>
                  <td className="num">{i + 1}</td>
                  <td><button type="button" className="link" onClick={() => onOpenTarget(s.targetId)}>{s.name}</button>
                    {!s.enabled && <span className="muted"> · de baja</span>}</td>
                  <td className="opt"><span className="kind-dot" style={{ background: KIND_COLOR[s.kind] }} />{KIND_LABEL[s.kind]}</td>
                  <td className="num">{fmt.format(s.mentions)}</td>
                  <td className="num" style={{ color: s.negative ? "var(--neg)" : undefined }}>
                    {fmt.format(s.negative)}{s.mentions ? ` (${Math.round((s.negative / s.mentions) * 100)}%)` : ""}
                  </td>
                  <td className="num opt">{fmt.format(s.severe)}</td>
                  <td className="num">{s.lastIndex == null ? "–" : s.lastIndex.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </section>
      </div>
    </div>
  );
}
