"use client";

import { useEffect, useState } from "react";
import { api, RISK_SURVEY, riskLevel, type Survey, type SurveyResponse } from "@/lib/api";
import { SurveyForm } from "./SurveyForm";

const date = (iso: string) => new Date(iso).toLocaleDateString("es-MX", { day: "2-digit", month: "short", year: "numeric" });

/** Resultado del último cuestionario de riesgo del objetivo; abre el formulario para contestarlo o actualizarlo. */
export function SurveyCard({ targetId, targetName }: { targetId: string; targetName: string }) {
  const [survey, setSurvey] = useState<Survey | null>(null);
  const [history, setHistory] = useState<SurveyResponse[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.survey(RISK_SURVEY).then(setSurvey).catch(() => {});
  }, []);
  useEffect(() => {
    let cancelled = false;
    setHistory(null);
    api.surveyResponses(targetId, RISK_SURVEY, 2).then((h) => !cancelled && setHistory(h)).catch(() => !cancelled && setHistory([]));
    return () => { cancelled = true; };
  }, [targetId]);

  const latest = history?.[0] ?? null;
  const before = history?.[1] ?? null;
  const level = latest?.score != null ? riskLevel(latest.score) : null;
  const delta = latest?.score != null && before?.score != null ? latest.score - before.score : null;
  const sections = survey ? [...survey.sections].sort((a, b) => a.order - b.order) : [];

  return (
    <section className="card span-3">
      <h2>Cuestionario de riesgo</h2>
      {history === null ? <div className="empty">Cargando…</div> : !latest ? (
        <p className="muted">Sin contestar. Mientras tanto el índice usa solo medios; el cuestionario aporta el 40 %.</p>
      ) : (
        <>
          <div className="kpi">{latest.score?.toFixed(1)} <small>/ 100</small></div>
          <p>
            {level && <span className="pill" style={{ background: level.color }}>{level.label}</span>}
            <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
              {date(latest.submittedAt)}
              {delta != null && delta !== 0 && ` · ${delta > 0 ? "+" : ""}${delta.toFixed(1)} vs. anterior`}
            </span>
          </p>
          {sections.map((s) => {
            const v = latest.sectionValues[s.id] ?? 0;
            return (
              <div key={s.id} style={{ fontSize: 12, marginBottom: 6 }}>
                {s.name} · {v} <span className="muted">(peso {Math.round(s.weight * 100)} %)</span>
                <div className="bar"><div style={{ width: `${Math.min(Math.max(v, 0), 100)}%`, background: s.color }} /></div>
              </div>
            );
          })}
        </>
      )}
      <button type="button" disabled={!survey || history === null} onClick={() => setOpen(true)} style={{ marginTop: 8 }}>
        {latest ? "Actualizar respuestas" : "Contestar cuestionario"}
      </button>
      {open && survey && (
        <SurveyForm targetId={targetId} targetName={targetName} survey={survey} previous={latest}
          onClose={() => setOpen(false)}
          onSaved={(r) => { setHistory((h) => [r, ...(h ?? [])].slice(0, 2)); setOpen(false); }} />
      )}
    </section>
  );
}
