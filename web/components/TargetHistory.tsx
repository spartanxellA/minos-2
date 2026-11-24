"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useState } from "react";
import { api, SOURCE_LABEL, type HistoryFilters, type TargetHistory as History } from "@/lib/api";
import { periodLabel, riskBands, SENT } from "@/lib/charts";
import { useI18n } from "@/lib/i18n";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { EChart } from "./EChart";

const pct = (n: number, total: number) => (total ? Math.round((n / total) * 100) : 0);

/** Historial de un solo objetivo dentro de «Análisis»: menciones por sentimiento y medio, e índice de riesgo. */
export function TargetHistory({ targetId, filters, onOpenTarget }: {
  targetId: string;
  filters: HistoryFilters;
  onOpenTarget: (id: string) => void;
}) {
  const phone = useMediaQuery(PHONE);
  const { t, tApi, lang, nf } = useI18n();
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { granularity, since, days, source } = filters;

  useEffect(() => {
    let stale = false;
    api.targetHistory(targetId, { granularity, since, days, source })
      .then((d) => { if (!stale) { setData(d); setError(null); } })
      .catch((err) => { if (!stale) { setData(null); setError((err as Error).message); } });
    return () => { stale = true; };
  }, [targetId, granularity, since, days, source]);

  const periods = data?.periods ?? [];
  const riskByPeriod = useMemo(() => new Map((data?.risk ?? []).map((r) => [r.period, r])), [data]);
  const sourceName = (s: string) => (SOURCE_LABEL[s] ? t(SOURCE_LABEL[s]) : s);

  const base = {
    grid: { left: phone ? 36 : 48, right: phone ? 8 : 16, top: 36, bottom: 28 },
    legend: { top: 0, type: "scroll" as const },
    xAxis: {
      type: "category" as const, data: periods.map((p) => periodLabel(p.period)),
      axisLabel: { hideOverlap: true }, axisTick: { alignWithLabel: true },
    },
  };

  const mentionsChart: EChartsOption = useMemo(() => ({
    ...base, yAxis: { type: "value", minInterval: 1 },
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
    series: SENT.map((s) => ({
      name: t(s.label), type: "bar", stack: "m", color: s.color, barMaxWidth: 36, data: periods.map((p) => p[s.key]),
    })),
  }), [data, phone, lang]);

  const sourcesChart: EChartsOption = useMemo(() => {
    const rows = data?.bySource ?? [];
    return {
      grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
      legend: { top: 0 },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
      xAxis: { type: "value", minInterval: 1 },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => sourceName(r.source)) },
      series: SENT.map((s) => ({
        name: t(s.label), type: "bar", stack: "s", color: s.color, barMaxWidth: 22, data: rows.map((r) => r[s.key]),
      })),
    };
  }, [data, lang]);

  const riskChart: EChartsOption = useMemo(() => ({
    ...base, yAxis: { type: "value", min: 0, max: 100, interval: 25 },
    tooltip: { trigger: "axis", confine: true, valueFormatter: (v: unknown) => (v == null ? t("sin dato") : Number(v).toFixed(1)) },
    series: ([["avg", t("Promedio"), "solid"], ["max", t("Máximo"), "dashed"]] as const).map(([key, name, line], i) => ({
      name, type: "line", color: i ? "#e07b00" : "#1668b7", lineStyle: { type: line }, symbolSize: 6, connectNulls: true,
      showSymbol: periods.length < 32 || (data?.risk.length ?? 0) < 2,
      data: periods.map((p) => riskByPeriod.get(p.period)?.[key] ?? null),
      markArea: i === 0 ? riskBands : undefined,
    })),
  }) as EChartsOption, [data, riskByPeriod, phone, lang]);

  if (error) return <p className="error">{tApi(error)}</p>;
  if (!data) return <div className="card empty">{t("Cargando…")}</div>;

  const { totals } = data;
  const empty = <div className="empty">{t("Sin menciones en este rango.")}</div>;
  // Lo más reciente primero; por día se saltan los que no tienen nada.
  const rows = periods.filter((p) => data.granularity !== "day" || p.mentions || riskByPeriod.has(p.period)).reverse();

  return (
    <div className="grid">
      <section className="card span-12 history-head">
        <div className="card-head">
          <h2>{t("Historial de {name}", { name: data.target.name })}{!data.target.enabled && ` · ${t("de baja")}`}</h2>
          <button type="button" className="link" onClick={() => onOpenTarget(targetId)}>{t("Abrir tablero")}</button>
        </div>
        <dl className="history-kpis">
          <div><dt>{t("Menciones")}</dt><dd>{nf.format(totals.mentions)}</dd></div>
          {SENT.map((s) => (
            <div key={s.key}>
              <dt><span className="kind-dot" style={{ background: s.color }} aria-hidden />{t(s.label)}</dt>
              <dd>{nf.format(totals[s.key])} <small>{pct(totals[s.key], totals.mentions)}%</small></dd>
            </div>
          ))}
          <div><dt>{t("Acusaciones graves")}</dt><dd>{nf.format(totals.severe)}</dd></div>
          <div><dt>{t("Índice actual")}</dt><dd>{data.lastIndex == null ? "–" : data.lastIndex.toFixed(1)} <small>/ 100</small></dd></div>
        </dl>
        <p className="muted hint">
          {periods.length > 0 && `${periodLabel(periods[0].period, true)} – ${periodLabel(periods[periods.length - 1].period, true)}`}
          {data.timezone === "UTC" ? " · UTC" : ""}
        </p>
      </section>

      <section className="card span-12">
        <h2>{t("Menciones en el tiempo, por sentimiento")}</h2>
        {totals.mentions ? <EChart replaceSeries option={mentionsChart} height={phone ? 240 : 300} /> : empty}
      </section>

      <section className="card span-5">
        <h2>{t("Menciones por medio")}</h2>
        {totals.mentions ? <EChart replaceSeries option={sourcesChart} height={Math.max(160, data.bySource.length * 34 + 64)} /> : empty}
      </section>

      <section className="card span-7">
        <h2>{t("Índice de riesgo en el tiempo")}</h2>
        {data.risk.length
          ? <EChart replaceSeries option={riskChart} height={phone ? 240 : 280} />
          : <div className="empty">{t("Sin cálculos del índice en este rango.")}</div>}
        {source && data.risk.length > 0 && <p className="muted hint">{t("El índice considera todos los medios, aunque filtres por uno.")}</p>}
      </section>

      <section className="card span-12">
        <h2>{t("Detalle por periodo")}</h2>
        {rows.length ? (
          <div className="scroll-x"><table className="ranking">
            <thead><tr>
              <th>{t("Periodo")}</th><th className="num">{t("Menciones")}</th><th className="num opt">{t("Positivas")}</th>
              <th className="num opt">{t("Neutras")}</th><th className="num">{t("Negativas")}</th>
              <th className="num opt">{t("Acusaciones graves")}</th><th className="num">{t("Índice promedio")}</th>
            </tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.period}>
                  <td>{periodLabel(p.period, true)}</td>
                  <td className="num">{nf.format(p.mentions)}</td>
                  <td className="num opt">{nf.format(p.positive)}</td>
                  <td className="num opt">{nf.format(p.neutral)}</td>
                  <td className="num" style={{ color: p.negative ? "var(--neg)" : undefined }}>
                    {nf.format(p.negative)}{p.mentions ? ` (${pct(p.negative, p.mentions)}%)` : ""}
                  </td>
                  <td className="num opt">{nf.format(p.severe)}</td>
                  <td className="num">{riskByPeriod.get(p.period)?.avg.toFixed(1) ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : empty}
      </section>
    </div>
  );
}
