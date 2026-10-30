"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useState } from "react";
import { api, can, GEO_METHOD_LABEL, KIND_LABEL, SOURCE_LABEL, type Alert, type Me, type Mention, type Sentiment, type Target } from "@/lib/api";
import { PasswordDialog, UsersDialog } from "./AccountDialogs";
import { SourcesDialog } from "./SourcesDialog";
import { AuditDialog } from "./AuditDialog";
import { Analytics } from "./Analytics";
import { ScreeningCard } from "./Screening";
import { WatchlistsDialog } from "./WatchlistsDialog";
import { TargetsDialog } from "./TargetsDialog";
import { useLiveTarget } from "@/lib/useLiveTarget";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { EChart } from "./EChart";
import { NewTargetForm } from "./NewTargetForm";
import { SurveyCard } from "./SurveyCard";
import { GeoMapCard } from "./GeoMap";
import { Logo } from "./Logo";

const SENT = { positive: { label: "Positivo", color: "#2e7d32" }, neutral: { label: "Neutro", color: "#8a94a0" }, negative: { label: "Negativo", color: "#d32f2f" } } as const;
const fmt = new Intl.NumberFormat("es-MX");
const time = (iso: string) => new Date(iso).toLocaleString("es-MX", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

const NOTIFY_KEY = "minos.notify";

export function Dashboard({ user, onLogout }: { user: Me; onLogout: () => void }) {
  const [dialog, setDialog] = useState<"users" | "password" | "sources" | "audit" | "watchlists" | "targets" | null>(null);
  const [sourceErrors, setSourceErrors] = useState(0);
  const [pendingMatches, setPendingMatches] = useState(0);
  const [targets, setTargets] = useState<Target[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [notify, setNotify] = useState(false);
  const [adding, setAdding] = useState(false);
  // "analytics": vista general de todos los sujetos en lugar del tablero de uno.
  const [view, setView] = useState<"target" | "analytics">("target");
  const phone = useMediaQuery(PHONE);
  const selectedName = targets.find((t) => t.id === selected)?.name ?? "";

  const onAlert = (a: Alert) => {
    if (!notify || typeof Notification === "undefined" || Notification.permission !== "granted") return;
    new Notification(`${a.title} · ${selectedName}`, { body: a.message, tag: a.id != null ? String(a.id) : undefined });
  };
  const live = useLiveTarget(selected, onAlert);
  const latest = live.latest;

  // Cuántas fuentes tienen algún objetivo con error, para avisar en el botón "Fuentes".
  useEffect(() => {
    const load = () => api.sources().then((s) => setSourceErrors(s.sources.filter((x) => x.errors.length).length)).catch(() => {});
    const loadMatches = () => api.matches("pending").then((m) => setPendingMatches(m.length)).catch(() => {});
    load();
    loadMatches();
    const timer = setInterval(() => { load(); loadMatches(); }, 5 * 60_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    try {
      setNotify(localStorage.getItem(NOTIFY_KEY) === "1" && Notification.permission === "granted");
    } catch {
      /* sin almacenamiento o sin notificaciones */
    }
    // Los avisos por correo, webhook y WhatsApp enlazan a /?target=<id>.
    const wanted = new URLSearchParams(window.location.search).get("target");
    api.targets().then((t) => {
      setTargets(t);
      setSelected((s) => s ?? t.find((x) => x.id === wanted)?.id ?? t.find((x) => x.enabled)?.id ?? null);
    }).catch(() => {});
  }, []);

  async function toggleNotify() {
    if (typeof Notification === "undefined") return;
    const next = !notify && (Notification.permission === "granted" || (await Notification.requestPermission()) === "granted");
    setNotify(next);
    try {
      localStorage.setItem(NOTIFY_KEY, next ? "1" : "0");
    } catch {
      /* sin almacenamiento */
    }
  }

  // Momentos en que se confirmó una coincidencia en listas negras: se marcan en la gráfica.
  const confirmations = (live.screening?.matches ?? []).filter((m) => m.status === "confirmed" && m.reviewedAt);
  const trend: EChartsOption = useMemo(() => ({
    grid: { left: phone ? 32 : 40, right: phone ? 8 : 16, top: 16, bottom: 28 },
    tooltip: { trigger: "axis", confine: true, valueFormatter: (v) => `${Number(v).toFixed(1)}` },
    xAxis: { type: "time", splitNumber: phone ? 3 : undefined, axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", min: 0, max: 100, interval: 25 },
    visualMap: { show: false, dimension: 1, pieces: [{ lte: 25, color: "#2e7d32" }, { gt: 25, lte: 50, color: "#c9a800" }, { gt: 50, color: "#d32f2f" }] },
    series: [{
      name: "Índice", type: "line", showSymbol: live.risk.length < 2, smooth: 0.2,
      data: live.risk.map((r) => [r.at, r.index]),
      markArea: { silent: true, itemStyle: { opacity: 0.06 }, data: [
        [{ yAxis: 0, itemStyle: { color: "#2e7d32" } }, { yAxis: 25 }],
        [{ yAxis: 25, itemStyle: { color: "#c9a800" } }, { yAxis: 50 }],
        [{ yAxis: 50, itemStyle: { color: "#d32f2f" } }, { yAxis: 100 }],
      ] },
      markLine: confirmations.length ? {
        symbol: "none", lineStyle: { color: "#d32f2f", type: "dashed" },
        label: { formatter: "Lista negra", fontSize: 10 },
        data: confirmations.map((m) => ({ xAxis: m.reviewedAt!, name: `${m.listedName} · ${m.sourceName}` })),
      } : undefined,
    }],
  }), [live.risk, phone, live.screening]);

  const radar: EChartsOption = useMemo(() => ({
    tooltip: { confine: true },
    radar: { indicator: [
      { name: "Negatividad", max: 100 }, { name: "Acusaciones", max: 100 },
      { name: "Volumen anómalo", max: 100 }, { name: "Cuestionario", max: 100 },
    ], radius: phone ? "58%" : "48%", axisName: { fontSize: 11 } },
    series: [{ type: "radar", areaStyle: { opacity: 0.2 }, data: [{
      name: "Factores", value: latest ? [latest.negativity * 100, latest.severity * 100, latest.volumeAnomaly * 100, latest.surveyScore ?? 0].map((v) => Math.round(v)) : [0, 0, 0, 0],
    }] }],
  }), [latest, phone]);

  const bySource: EChartsOption = useMemo(() => {
    const rows = live.breakdown?.bySourceAndSentiment ?? [];
    const sources = [...new Set(rows.map((r) => r.source))];
    return {
      grid: { left: 70, right: 16, top: 24, bottom: 24 },
      legend: { top: 0 },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
      xAxis: { type: "value" },
      yAxis: { type: "category", data: sources.map((s) => SOURCE_LABEL[s] ?? s) },
      series: (["positive", "neutral", "negative"] as const).map((k) => ({
        name: SENT[k].label, type: "bar", stack: "s", color: SENT[k].color,
        data: sources.map((s) => rows.find((r) => r.source === s && r.sentiment.toLowerCase() === k)?.count ?? 0),
      })),
    };
  }, [live.breakdown]);

  const selectedTarget = targets.find((t) => t.id === selected);
  // El selector muestra los activos; uno dado de baja solo aparece mientras está abierto (por ejemplo desde un aviso).
  const choices = targets.filter((t) => t.enabled || t.id === selected);

  function targetChanged(change: Target | { id: string; deleted: true }) {
    const next = "deleted" in change ? targets.filter((t) => t.id !== change.id) : targets.map((t) => (t.id === change.id ? change : t));
    setTargets(next);
    if (change.id === selected && ("deleted" in change || !change.enabled)) setSelected(next.find((t) => t.enabled)?.id ?? null);
  }

  return (
    <>
      <header className="top">
        <h1 className="brand"><Logo />min<span>OS</span> 2.0</h1>
        <select className="target" value={selected ?? ""} onChange={(e) => { setSelected(e.target.value); setView("target"); }} aria-label="Objetivo">
          {choices.map((t) => <option key={t.id} value={t.id}>{t.name} · {KIND_LABEL[t.kind]}{t.enabled ? "" : " (de baja)"}</option>)}
        </select>
        <div className="status"><span className={`dot ${live.status}`} />{live.status === "live" ? "En vivo" : live.status === "connecting" ? "Conectando…" : "Sin conexión"}</div>
        <button type="button" className={`notify ${notify ? "" : "ghost"}`} onClick={toggleNotify} aria-pressed={notify}
          title="Aviso del navegador cuando llegue una alerta del objetivo seleccionado">
          {notify ? "Avisos activados" : "Activar avisos"}
        </button>
        <button type="button" className={`sources ${view === "analytics" ? "" : "ghost"}`} aria-pressed={view === "analytics"}
          onClick={() => setView(view === "analytics" ? "target" : "analytics")}
          title="Sujetos más mencionados, por tipo, e históricos por mes y año">
          Análisis
        </button>
        <button type="button" className="ghost sources" onClick={() => setDialog("sources")}
          title="Qué fuentes están activas, qué trajeron y cuáles fallan">
          Fuentes{sourceErrors > 0 && <span className="badge" aria-label={`${sourceErrors} con error`}>{sourceErrors}</span>}
        </button>
        <button type="button" className="ghost sources" onClick={() => setDialog("watchlists")}
          title="Coincidencias pendientes de revisar y estado de las listas negras">
          Listas{pendingMatches > 0 && <span className="badge" aria-label={`${pendingMatches} pendientes`}>{pendingMatches}</span>}
        </button>
        <button type="button" className="ghost sources" onClick={() => setDialog("targets")}
          title="Editar, dar de baja y reactivar objetivos">
          Objetivos
        </button>
        <div className="spacer" />
        {can(user, "analyst") && (
          <button type="button" className={`add ${adding ? "" : "ghost"}`} onClick={() => setAdding(!adding)} aria-expanded={adding}>
            + Objetivo
          </button>
        )}
        {user.authMode === "local" && (
          <details className="account">
            <summary title={user.email}>{user.name}</summary>
            <div className="menu" onClick={(e) => e.currentTarget.closest("details")?.removeAttribute("open")}>
              <div className="who">{user.email}<br /><span className="muted">{user.roleLabel}</span></div>
              {can(user, "admin") && <button type="button" className="ghost" onClick={() => setDialog("users")}>Usuarios</button>}
              {can(user, "admin") && <button type="button" className="ghost" onClick={() => setDialog("audit")}>Auditoría</button>}
              <button type="button" className="ghost" onClick={() => setDialog("password")}>Contraseña</button>
              <button type="button" className="ghost" onClick={onLogout}>Salir</button>
            </div>
          </details>
        )}
      </header>
      {adding && (
        <div className="new-panel">
          <NewTargetForm onCancel={() => setAdding(false)}
            onCreated={(t) => { setTargets((p) => [...p, t]); setSelected(t.id); setAdding(false); }} />
        </div>
      )}
      {dialog === "users" && <UsersDialog me={user} onClose={() => setDialog(null)} />}
      {dialog === "sources" && <SourcesDialog onClose={() => setDialog(null)} onLoaded={setSourceErrors} />}
      {dialog === "password" && <PasswordDialog onClose={() => setDialog(null)} />}
      {dialog === "audit" && <AuditDialog onClose={() => setDialog(null)} />}
      {dialog === "targets" && <TargetsDialog user={user} onClose={() => setDialog(null)} onChanged={targetChanged} />}
      {dialog === "watchlists" && (
        <WatchlistsDialog canReview={can(user, "analyst")} isAdmin={can(user, "admin")}
          onClose={() => { setDialog(null); live.refreshScreening(); }} onChanged={setPendingMatches} />
      )}

      <main>
        {view === "analytics" ? (
          <Analytics onOpenTarget={(id) => { setSelected(id); setView("target"); window.scrollTo({ top: 0 }); }} />
        ) : !selectedTarget ? (
          <div className="card empty">
            {targets.length > 0 ? "Todos los objetivos están dados de baja; se pueden reactivar en «Objetivos»." : can(user, "analyst")
              ? "Agrega una persona, empresa, institución, área de gobierno o país para empezar a monitorear."
              : "Todavía no hay objetivos. Un analista o administrador puede agregarlos."}
          </div>
        ) : (
          <div className="grid">
            {!selectedTarget.enabled && (
              <div className="card span-12 disclaimer" role="status" style={{ margin: 0 }}>
                <b>Dado de baja</b> el {selectedTarget.deactivatedAt ? new Date(selectedTarget.deactivatedAt).toLocaleDateString("es-MX", { dateStyle: "medium" }) : "—"}
                {selectedTarget.deactivationReason && ` · “${selectedTarget.deactivationReason}”`}. Ya no se busca ni se recalcula; lo que ves es su historia.
              </div>
            )}
            <section className="card span-3">
              <h2>Índice de riesgo reputacional</h2>
              <div className="kpi">{latest ? latest.index.toFixed(1) : "–"} <small>/ 100</small></div>
              {latest && <p><span className="pill" style={{ background: latest.color }}>{latest.label}</span></p>}
              <div className="drivers">
                <span>Medios</span><b>{latest ? latest.mediaScore.toFixed(1) : "–"}</b>
                <span>Cuestionario</span><b>{latest?.surveyScore != null ? latest.surveyScore.toFixed(1) : "sin contestar"}</b>
                <span>Menciones 24 h</span><b>{latest ? fmt.format(latest.mentions) : "–"}</b>
                {latest && latest.watchlistImpact > 0 && (
                  <><span>Listas negras</span><b style={{ color: "var(--neg)" }}>+{latest.watchlistImpact.toFixed(1)}</b></>
                )}
              </div>
              {latest && (
                <div style={{ marginTop: 12 }}>
                  {(["positive", "neutral", "negative"] as const).map((k) => {
                    const v = latest[k]; const pct = latest.mentions ? (v / latest.mentions) * 100 : 0;
                    return (
                      <div key={k} style={{ fontSize: 12, marginBottom: 6 }}>
                        {SENT[k].label} · {fmt.format(v)} ({pct.toFixed(0)}%)
                        <div className="bar"><div style={{ width: `${pct}%`, background: SENT[k].color }} /></div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="card span-9">
              <h2>Evolución del índice</h2>
              {live.risk.length ? <EChart option={trend} height={phone ? 220 : 300} /> : <div className="empty">Esperando el primer cálculo…</div>}
            </section>

            <section className="card span-3">
              <h2>Factores de riesgo</h2>
              <EChart option={radar} height={phone ? 240 : 260} />
            </section>

            <section className="card span-3">
              <h2>Sentimiento por fuente (24 h)</h2>
              <EChart option={bySource} height={phone ? 200 : 260} />
            </section>

            <SurveyCard key={selectedTarget.id} targetId={selectedTarget.id} targetName={selectedTarget.name}
              surveyScore={latest?.surveyScore} canAnswer={can(user, "analyst")} />

            <ScreeningCard key={`s-${selectedTarget.id}`} target={selectedTarget} screening={live.screening}
              canReview={can(user, "analyst")} onChanged={() => { live.refreshScreening(); api.matches("pending").then((m) => setPendingMatches(m.length)).catch(() => {}); }}
              onTargetSaved={(t) => setTargets((p) => p.map((x) => (x.id === t.id ? t : x)))} />

            <section className="card span-3">
              <h2>Alertas</h2>
              {live.alerts.length === 0 ? <div className="empty">Sin alertas</div> : (
                <ul className="feed" style={{ maxHeight: 260 }}>
                  {live.alerts.map((a, i) => (
                    <li key={a.id ?? i}><b>{a.title}</b><div>{a.message}</div>{a.at && <div className="meta">{time(a.at)}</div>}</li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card span-5">
              <h2>Menciones en vivo</h2>
              {live.mentions.length === 0 ? <div className="empty">Aún no hay menciones.</div> : (
                <ul className="feed">
                  {live.mentions.map((m) => (
                    <li key={m.id}>
                      <a href={m.url} target="_blank" rel="noreferrer">{m.text}</a>
                      <div className="meta">
                        {can(user, "analyst")
                          ? <SentimentPicker mention={m} onSaved={live.replaceMention} />
                          : <span className={`tag ${m.sentiment}`}>{SENT[m.sentiment].label}</span>}
                        {m.corrected && (
                          <span title={`Corregido por ${m.correctedBy ?? "un analista"}; el análisis automático dijo ${SENT[m.originalSentiment ?? m.sentiment].label}`}>
                            ✎ corregido
                          </span>
                        )}
                        {m.severe && <span className="tag severe">Acusación grave</span>}
                        {m.topic && <span>#{m.topic}</span>}
                        <span>{SOURCE_LABEL[m.source] ?? m.source}</span>
                        <span>{m.author}{m.followers ? ` · ${fmt.format(m.followers)} seguidores` : ""}</span>
                        {m.place && (
                          <span className="place" title={`Ubicación para el mapa: ${m.placeMethod ? GEO_METHOD_LABEL[m.placeMethod] : ""}`}>⌖ {m.place}</span>
                        )}
                        <span>{time(m.publishedAt)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card span-4">
              <h2>Cuentas con mayor alcance (24 h)</h2>
              <div className="scroll-x"><table>
                <thead><tr><th>Cuenta</th><th className="num">Seguidores</th><th className="num">Menciones</th><th className="num">Negativas</th></tr></thead>
                <tbody>
                  {(live.breakdown?.influencers ?? []).map((u) => (
                    <tr key={u.author}><td>{u.author}</td><td className="num">{fmt.format(u.followers)}</td><td className="num">{u.mentions}</td><td className="num" style={{ color: u.negative ? "var(--neg)" : undefined }}>{u.negative}</td></tr>
                  ))}
                </tbody>
              </table></div>
            </section>

            <GeoMapCard targetId={selectedTarget.id} targetName={selectedTarget.name} canLocate={can(user, "analyst")}
              refreshKey={live.mentions.length ? Date.parse(live.mentions[0].publishedAt) : undefined} />
          </div>
        )}
      </main>
    </>
  );
}


/** Etiqueta de sentimiento que un analista puede cambiar; la corrección cuenta en el índice y enseña al análisis. */
function SentimentPicker({ mention: m, onSaved }: { mention: Mention; onSaved: (m: Mention) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <select className={`tag ${m.sentiment} sentiment-picker`} value={m.sentiment} disabled={saving}
        aria-label="Corregir sentimiento" title="Corregir sentimiento"
        onChange={(e) => {
          setSaving(true);
          setError(null);
          api.correctSentiment(m.id, e.target.value as Sentiment)
            .then(onSaved)
            .catch((err: Error) => setError(err.message))
            .finally(() => setSaving(false));
        }}>
        {(Object.keys(SENT) as Sentiment[]).map((k) => <option key={k} value={k}>{SENT[k].label}</option>)}
      </select>
      {error && <span className="error" role="alert">{error}</span>}
    </>
  );
}
