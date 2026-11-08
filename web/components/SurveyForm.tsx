"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Survey, type SurveyResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** El cuestionario de riesgo por secciones, precargado con las últimas respuestas del objetivo. */
export function SurveyForm({ targetId, targetName, survey, previous, onClose, onSaved }: {
  targetId: string;
  targetName: string;
  survey: Survey;
  previous: SurveyResponse | null;
  onClose: () => void;
  onSaved: (r: SurveyResponse) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const sections = useMemo(() => [...survey.sections].sort((a, b) => a.order - b.order), [survey]);
  const [answers, setAnswers] = useState<Record<string, string>>(previous?.answers ?? {});
  const [step, setStep] = useState(0);
  const [showMissing, setShowMissing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Las preguntas vienen del servidor en español; su traducción está en lib/messages/survey.ts.
  const { t, tApi } = useI18n();

  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [step]);

  const missing = (i: number) => sections[i].questions.filter((q) => q.required && !answers[q.id]);
  const total = sections.reduce((n, s) => n + s.questions.length, 0);
  const answered = sections.reduce((n, s) => n + s.questions.filter((q) => answers[q.id]).length, 0);
  const section = sections[step];
  const last = step === sections.length - 1;

  async function save() {
    const firstIncomplete = sections.findIndex((_, i) => missing(i).length > 0);
    if (firstIncomplete >= 0) {
      setShowMissing(true);
      setStep(firstIncomplete);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.submitSurvey(targetId, survey.id, answers));
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <dialog ref={dialog} className="survey" onClose={onClose} aria-labelledby="survey-title">
      <header>
        <div>
          <h2 id="survey-title">{t("Cuestionario de riesgo")}</h2>
          <div className="meta">{targetName} · {t("{answered} de {total} contestadas", { answered, total })}</div>
        </div>
        <button type="button" className="ghost" onClick={() => dialog.current?.close()} aria-label={t("Cerrar")}>✕</button>
      </header>

      <nav className="steps">
        {sections.map((s, i) => {
          const done = s.questions.filter((q) => answers[q.id]).length;
          const incomplete = showMissing && missing(i).length > 0;
          return (
            <button key={s.id} type="button" className={i === step ? "on" : ""} onClick={() => setStep(i)}
              style={{ borderColor: s.color }} aria-current={i === step ? "step" : undefined}>
              {tApi(s.name)} <small className={incomplete ? "warn" : ""}>{done}/{s.questions.length}</small>
            </button>
          );
        })}
      </nav>

      <div className="body" ref={body}>
        {step === 0 && <p className="intro">{tApi(section.description)}</p>}
        {section.questions.map((q) => {
          const flagged = showMissing && q.required && !answers[q.id];
          return (
            <fieldset key={q.id} className={flagged ? "missing" : ""}>
              <legend>{tApi(q.text)}</legend>
              {q.subtext && <div className="sub">{tApi(q.subtext)}</div>}
              <div className="options">
                {q.options.map((o) => (
                  <label key={o.value} className={answers[q.id] === o.value ? "on" : ""}>
                    <input type="radio" name={q.id} value={o.value} checked={answers[q.id] === o.value}
                      onChange={() => setAnswers((a) => ({ ...a, [q.id]: o.value }))} />
                    {tApi(o.label)}
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}
      </div>

      <footer>
        {error && <span className="error">{error}</span>}
        {showMissing && answered < total && <span className="error">{t("Faltan {n} respuestas.", { n: total - answered })}</span>}
        <div style={{ flex: 1 }} />
        <button type="button" className="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>{t("Anterior")}</button>
        {last
          ? <button type="button" disabled={saving} onClick={save}>{saving ? t("Guardando…") : t("Guardar y recalcular")}</button>
          : <button type="button" onClick={() => setStep(step + 1)}>{t("Siguiente")}</button>}
      </footer>
    </dialog>
  );
}
