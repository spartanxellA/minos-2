"use client";

import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, GEO_METHOD_LABEL, SOURCE_LABEL, type GeoBasis, type GeoOverview, type GeoPlace,
} from "@/lib/api";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { EChart } from "./EChart";

const fmt = new Intl.NumberFormat("es-MX");
const pct = (n: number, d: number) => (d ? `${Math.round((n / d) * 100)}%` : "0%");

const MX_STATES: Record<string, string> = {
  "MX-AGU": "Aguascalientes", "MX-BCN": "Baja California", "MX-BCS": "Baja California Sur", "MX-CAM": "Campeche",
  "MX-CHP": "Chiapas", "MX-CHH": "Chihuahua", "MX-CMX": "Ciudad de México", "MX-COA": "Coahuila", "MX-COL": "Colima",
  "MX-DUR": "Durango", "MX-GUA": "Guanajuato", "MX-GRO": "Guerrero", "MX-HID": "Hidalgo", "MX-JAL": "Jalisco",
  "MX-MEX": "Estado de México", "MX-MIC": "Michoacán", "MX-MOR": "Morelos", "MX-NAY": "Nayarit", "MX-NLE": "Nuevo León",
  "MX-OAX": "Oaxaca", "MX-PUE": "Puebla", "MX-QUE": "Querétaro", "MX-ROO": "Quintana Roo", "MX-SLP": "San Luis Potosí",
  "MX-SIN": "Sinaloa", "MX-SON": "Sonora", "MX-TAB": "Tabasco", "MX-TAM": "Tamaulipas", "MX-TLA": "Tlaxcala",
  "MX-VER": "Veracruz", "MX-YUC": "Yucatán", "MX-ZAC": "Zacatecas",
};
const countryName = (() => {
  let names: Intl.DisplayNames | null = null;
  try { names = new Intl.DisplayNames(["es"], { type: "region" }); } catch { /* navegador sin DisplayNames */ }
  return (code: string) => names?.of(code) ?? code;
})();

// Los mapas (≈150 KB) se cargan solo cuando se abre la tarjeta.
let mapsReady: Promise<void> | null = null;
function loadMaps() {
  mapsReady ??= Promise.all([import("@/assets/geo/world.json"), import("@/assets/geo/mexico.json")]).then(([world, mexico]) => {
    echarts.registerMap("minos-world", (world as any).default ?? world);
    echarts.registerMap("minos-mexico", (mexico as any).default ?? mexico);
  });
  return mapsReady;
}

/** Color de un punto según la proporción de menciones negativas, con los mismos cortes que el índice. */
function negativeColor(share: number) {
  return share > 0.5 ? "#d32f2f" : share > 0.25 ? "#c9a800" : "#2e7d32";
}

function useDark() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(q.matches);
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return dark;
}

/** Mapa de dónde se genera la información sobre un objetivo: por estado de México o por país, con ciudades como puntos. */
export function GeoMapCard({ targetId, targetName, canLocate, refreshKey }: {
  targetId: string;
  targetName: string;
  canLocate: boolean;
  /** Cambia cuando llegan menciones nuevas, para volver a pedir los datos. */
  refreshKey?: number;
}) {
  const phone = useMediaQuery(PHONE);
  const dark = useDark();
  const [scope, setScope] = useState<"mx" | "world">("mx");
  const [days, setDays] = useState(30);
  const [basis, setBasis] = useState<GeoBasis>("all");
  const [data, setData] = useState<GeoOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [locating, setLocating] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => { loadMaps().then(() => setReady(true)).catch((e) => setError(String(e))); }, []);

  // Las menciones en vivo piden datos nuevos, pero a lo más una vez por minuto.
  const lastLive = useRef(0);
  const [liveTick, setLiveTick] = useState(0);
  useEffect(() => {
    if (refreshKey === undefined || Date.now() - lastLive.current < 60_000) return;
    lastLive.current = Date.now();
    setLiveTick((n) => n + 1);
  }, [refreshKey]);

  // Al abrir un objetivo se elige el mapa: México, salvo que casi todo venga de fuera.
  const scoped = useRef<string | null>(null);
  useEffect(() => {
    let stale = false;
    api.geo(targetId, days, basis)
      .then((d) => {
        if (stale) return;
        setData(d);
        setError(null);
        if (scoped.current !== targetId && d.located) {
          scoped.current = targetId;
          setScope((d.countries.find((c) => c.code === "MX")?.count ?? 0) >= d.located / 2 ? "mx" : "world");
        }
      })
      .catch((e: Error) => { if (!stale) setError(e.message); });
    return () => { stale = true; };
  }, [targetId, days, basis, reload, liveTick]);

  const points: GeoPlace[] = useMemo(() => (data?.places ?? []).filter((p) =>
    // Los estados también van como punto: la Ciudad de México apenas se ve como área.
    p.precision !== "country" && (scope === "world" || p.country === "MX"),
  ), [data, scope]);
  const mxWithoutState = useMemo(() => {
    const mx = data?.countries.find((c) => c.code === "MX")?.count ?? 0;
    return mx - (data?.regions ?? []).reduce((s, r) => s + r.count, 0);
  }, [data]);

  const option: EChartsOption = useMemo(() => {
    const areas = scope === "mx" ? data?.regions ?? [] : data?.countries ?? [];
    const max = Math.max(1, ...areas.map((a) => a.count));
    const maxPoint = Math.max(1, ...points.map((p) => p.count));
    const label = (code: string) => (scope === "mx" ? MX_STATES[code] ?? code : countryName(code));
    const base = dark ? "#20262e" : "#eef1f4";
    const border = dark ? "#3a424c" : "#c9d0d8";
    return {
      tooltip: {
        trigger: "item", confine: true,
        formatter: (p: any) => {
          if (p.seriesType === "scatter" || p.seriesType === "effectScatter") {
            const d = p.data as { name: string; count: number; negative: number };
            return `<b>${d.name}</b><br/>${fmt.format(d.count)} menciones · ${pct(d.negative, d.count)} negativas`;
          }
          const d = p.data as { count?: number; negative?: number } | undefined;
          return d?.count ? `<b>${label(p.name)}</b><br/>${fmt.format(d.count)} menciones · ${pct(d.negative ?? 0, d.count)} negativas`
            : `${label(p.name)}<br/>Sin menciones ubicadas`;
        },
      },
      visualMap: {
        type: "continuous", min: 0, max, seriesIndex: 0, calculable: false, orient: "horizontal",
        left: 8, bottom: 4, itemWidth: 10, itemHeight: phone ? 90 : 120, text: [fmt.format(max), "0"],
        textStyle: { color: dark ? "#9aa4af" : "#5b6470", fontSize: 11 },
        inRange: { color: dark ? ["#1d2a3a", "#5aa0f2"] : ["#dbe8f6", "#1668b7"] },
        outOfRange: { color: base },
      },
      geo: {
        map: scope === "mx" ? "minos-mexico" : "minos-world",
        roam: !phone, scaleLimit: { min: 1, max: 12 },
        // México llena la tarjeta; el mundo (sin la Antártida) se ajusta solo.
        ...(scope === "mx" ? { layoutCenter: ["50%", "48%"], layoutSize: "118%" } : { top: 8, bottom: 28 }),
        itemStyle: { areaColor: base, borderColor: border, borderWidth: 0.6 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: dark ? "#2d3743" : "#cfe0f3" } },
        select: { disabled: true },
      },
      series: [
        {
          type: "map", geoIndex: 0,
          data: areas.map((a) => ({ name: a.code, value: a.count, count: a.count, negative: a.negative })),
        },
        {
          type: "scatter", coordinateSystem: "geo", zlevel: 1,
          // En el mapa mundial las ciudades de México quedan juntas: puntos más chicos.
          symbolSize: (v: number[]) => (scope === "mx" ? 7 + 27 * Math.sqrt(v[2] / maxPoint) : 4 + 14 * Math.sqrt(v[2] / maxPoint)),
          itemStyle: { borderColor: dark ? "#0f1216" : "#ffffff", borderWidth: 1, opacity: 0.88 },
          label: {
            show: !phone, position: "right", fontSize: 11, color: dark ? "#e8ebef" : "#1b1f24",
            formatter: (p: any) => (p.dataIndex < 6 ? p.data.name.split(",")[0] : ""),
          },
          labelLayout: { hideOverlap: true },
          data: points.map((p) => ({
            name: p.name, value: [p.lon, p.lat, p.count], count: p.count, negative: p.negative,
            itemStyle: { color: negativeColor(p.count ? p.negative / p.count : 0) },
          })),
        },
      ],
    };
  }, [data, points, scope, phone, dark]);

  const shown = (scope === "mx" ? data?.places.filter((p) => p.country === "MX") : data?.places) ?? [];

  async function locatePending() {
    setLocating(true);
    try {
      await api.locatePending(targetId);
      setReload((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLocating(false);
    }
  }

  return (
    <section className="card span-12 geo-card">
      <div className="card-head">
        <h2>¿Desde dónde se habla de {targetName}?</h2>
        <div className="geo-controls">
          <div className="seg small" role="group" aria-label="Mapa">
            <button type="button" className={scope === "mx" ? "" : "ghost"} onClick={() => setScope("mx")}>México</button>
            <button type="button" className={scope === "world" ? "" : "ghost"} onClick={() => setScope("world")}>Mundo</button>
          </div>
          <select aria-label="Periodo" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Últimas 24 h</option>
            <option value={7}>Últimos 7 días</option>
            <option value={30}>Últimos 30 días</option>
            <option value={90}>Últimos 90 días</option>
            <option value={365}>Último año</option>
          </select>
          <select aria-label="Qué ubicación usar" value={basis} onChange={(e) => setBasis(e.target.value as GeoBasis)}>
            <option value="all">Origen y lugar mencionado</option>
            <option value="origin">Solo origen del autor o medio</option>
            <option value="text">Solo lugar mencionado</option>
          </select>
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="geo-body">
        <div className="geo-map">
          {!ready || !data ? <div className="empty">Cargando mapa…</div>
            : <EChart option={option} height={phone ? 300 : 440} replaceSeries />}
        </div>

        <aside className="geo-side">
          {data && (
            <>
              <div className="geo-coverage">
                <div className="kpi">{pct(data.located, data.total)}</div>
                <div>
                  <b>{fmt.format(data.located)}</b> de {fmt.format(data.total)} menciones tienen ubicación
                  <div className="muted">
                    {data.byMethod.map((m) => `${GEO_METHOD_LABEL[m.method] ?? m.method} ${fmt.format(m.count)}`).join(" · ") || "Ninguna todavía"}
                  </div>
                </div>
              </div>

              {shown.length > 0 ? (
                <div className="scroll-x"><table>
                  <thead><tr><th>Lugar</th><th className="num">Menciones</th><th className="num">Negativas</th></tr></thead>
                  <tbody>
                    {shown.slice(0, 8).map((p) => (
                      <tr key={p.name}>
                        <td><span className="dot" style={{ background: negativeColor(p.count ? p.negative / p.count : 0) }} />{p.name}</td>
                        <td className="num">{fmt.format(p.count)}</td>
                        <td className="num" style={{ color: p.negative ? "var(--neg)" : undefined }}>{pct(p.negative, p.count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              ) : <div className="empty">Sin menciones ubicadas {scope === "mx" ? "en México " : ""}en este periodo.</div>}

              {scope === "mx" && mxWithoutState > 0 && (
                <p className="muted hint">{fmt.format(mxWithoutState)} solo dicen «México», sin estado; cuentan en el mapa mundial.</p>
              )}

              {data.bySource.length > 0 && (
                <p className="muted hint">
                  Por fuente: {data.bySource.map((s) => `${SOURCE_LABEL[s.source] ?? s.source} ${pct(s.located, s.total)}`).join(" · ")}
                </p>
              )}

              {canLocate && data.pending > 0 && (
                <button type="button" className="ghost" disabled={locating} onClick={locatePending}>
                  {locating ? "Ubicando…" : `Ubicar ${fmt.format(data.pending)} menciones anteriores`}
                </button>
              )}

              <details className="geo-help">
                <summary>¿De dónde sale la ubicación?</summary>
                <p>
                  Del dato más confiable que dé cada fuente: la geoetiqueta de la publicación (X, muy pocas veces), la ubicación
                  que el autor escribió en su perfil (X), el país del canal (YouTube), la comunidad (Reddit) o la sede del medio
                  (Noticias). Si no hay ninguno, el lugar que más se nombra en el texto, que dice de dónde trata la nota y no
                  desde dónde se escribió. Bluesky, Facebook e Instagram no comparten ubicación. Lo que no se puede ubicar no
                  aparece en el mapa. El color de cada punto es la proporción de menciones negativas: verde hasta 25 %, amarillo
                  hasta 50 %, rojo arriba de 50 %.
                </p>
              </details>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
