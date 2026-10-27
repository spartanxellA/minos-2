"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useState } from "react";
import { api, can, KIND_LABEL, SOURCE_LABEL, type Alert, type Me, type Target } from "@/lib/api";
import { PasswordDialog, UsersDialog } from "./AccountDialogs";
import { SourcesDialog } from "./SourcesDialog";
import { AuditDialog } from "./AuditDialog";
import { useLiveTarget } from "@/lib/useLiveTarget";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { EChart } from "./EChart";
import { NewTargetForm } from "./NewTargetForm";
import { SurveyCard } from "./SurveyCard";
import { Logo } from "./Logo";

const SENT = { positive: { label: "Positivo", color: "#2e7d32" }, neutral: { label: "Neutro", color: "#8a94a0" }, negative: { label: "Negativo", color: "#d32f2f" } } as const;
const fmt = new Intl.NumberFormat("es-MX");
const time = (iso: string) => new Date(iso).toLocaleString("es-MX", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

const NOTIFY_KEY = "minos.notify";

export function Dashboard({ user, onLogout }: { user: Me; onLogout: () => void }) {
  const [dialog, setDialog] = useState<"users" | "password" | "sources" | "audit" | null>(null);
  const [sourceErrors, setSourceErrors] = useState(0);
  const [targets, setTargets] = useState<Target[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [notify, setNotify] = useState(false);
  const [adding, setAdding] = useState(false);
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
    load();
    const timer = setInterval(load, 5 * 60_000);
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
      setSelected((s) => s ?? t.find((x) => x.id === wanted)?.id ?? t[0]?.id ?? null);
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
    }],
  }), [live.risk, phone]);

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

  return (
    <>
      <header className="top">
        <h1 className="brand"><Logo />min<span>OS</span> 2.0</h1>
        <select className="target" value={selected ?? ""} onChange={(e) => setSelected(e.target.value)} aria-label="Objetivo">
          {targets.map((t) => <option key={t.id} value={t.id}>{t.name} · {KIND_LABEL[t.kind]}</option>)}
        </select>
        <div className="status"><span className={`dot ${live.status}`} />{live.status === "live" ? "En vivo" : live.status === "connecting" ? "Conectando…" : "Sin conexión"}</div>
        <button type="button" className={`notify ${notify ? "" : "ghost"}`} onClick={toggleNotify} aria-pressed={notify}
          title="Aviso del navegador cuando llegue una alerta del objetivo seleccionado">
          {notify ? "Avisos activados" : "Activar avisos"}
        </button>
        <button type="button" className="ghost sources" onClick={() => setDialog("sources")}
          title="Qué fuentes están activas, qué trajeron y cuáles fallan">
          Fuentes{sourceErrors > 0 && <span className="badge" aria-label={`${sourceErrors} con error`}>{sourceErrors}</span>}
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

      <main>
        {!selectedTarget ? (
          <div className="card empty">
            {can(user, "analyst")
              ? "Agrega una persona, empresa, institución, área de gobierno o país para empezar a monitorear."
              : "Todavía no hay objetivos. Un analista o administrador puede agregarlos."}
          </div>
        ) : (
          <div className="grid">
            <section className="card span-3">
              <h2>Índice de riesgo reputacional</h2>
              <div className="kpi">{latest ? latest.index.toFixed(1) : "–"} <small>/ 100</small></div>
              {latest && <p><span className="pill" style={{ background: latest.color }}>{latest.label}</span></p>}
              <div className="drivers">
                <span>Medios</span><b>{latest ? latest.mediaScore.toFixed(1) : "–"}</b>
                <span>Cuestionario</span><b>{latest?.surveyScore != null ? latest.surveyScore.toFixed(1) : "sin contestar"}</b>
                <span>Menciones 24 h</span><b>{latest ? fmt.format(latest.mentions) : "–"}</b>
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

            <section className="card span-7">
              <h2>Menciones en vivo</h2>
              {live.mentions.length === 0 ? <div className="empty">Aún no hay menciones.</div> : (
                <ul className="feed">
                  {live.mentions.map((m) => (
                    <li key={m.id}>
                      <a href={m.url} target="_blank" rel="noreferrer">{m.text}</a>
                      <div className="meta">
                        <span className={`tag ${m.sentiment}`}>{SENT[m.sentiment].label}</span>
                        {m.severe && <span className="tag severe">Acusación grave</span>}
                        {m.topic && <span>#{m.topic}</span>}
                        <span>{SOURCE_LABEL[m.source] ?? m.source}</span>
                        <span>{m.author}{m.followers ? ` · ${fmt.format(m.followers)} seguidores` : ""}</span>
                        <span>{time(m.publishedAt)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card span-5">
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
          </div>
        )}
      </main>
    </>
  );
}
