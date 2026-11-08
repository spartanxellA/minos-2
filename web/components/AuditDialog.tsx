"use client";

import { Fragment, useEffect, useState } from "react";
import { api, auditCsvUrl, KIND_LABEL, ROLE_LABEL, type AuditEvent, type AuditFilters, type Role, type TargetKind } from "@/lib/api";
import { Modal } from "./AccountDialogs";
import { locale, msg, translate as t, useI18n } from "@/lib/i18n";

const FIELD_LABEL: Record<string, string> = {
  name: msg("Nombre"), email: msg("Correo"), role: msg("Rol"), active: msg("Activa"), kind: msg("Tipo"), aliases: msg("Alias"),
  keywords: msg("Palabras clave"), excludedTerms: msg("Términos excluidos"), handles: msg("Cuentas"), enabled: msg("Activo"),
  birthDate: msg("Fecha de nacimiento"), nationality: msg("Nacionalidad"), identifiers: msg("Documentos"),
};
const REASON_LABEL: Record<string, string> = {
  wrong_password: msg("contraseña incorrecta"), unknown_account: msg("correo sin cuenta"), inactive: msg("cuenta desactivada"),
  locked: msg("correo bloqueado por intentos"), ip_blocked: msg("IP bloqueada por intentos"),
};
const GROUPS: [string, string][] = [
  ["auth.", msg("Sesiones (todas)")], ["user.", msg("Cuentas (todas)")], ["target.", msg("Objetivos (todos)")],
];

function show(field: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? t("sí") : t("no");
  if (field === "role") return ROLE_LABEL[value as Role] ? t(ROLE_LABEL[value as Role]) : String(value);
  if (field === "kind") return KIND_LABEL[value as TargetKind] ? t(KIND_LABEL[value as TargetKind]) : String(value);
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? entries.map(([k, v]) => `${k}: ${v}`).join(", ") : "—";
  }
  return String(value);
}

const when = (iso: string) => new Date(iso).toLocaleString(locale(), { dateStyle: "short", timeStyle: "medium" });

/** Fecha del calendario (día local) → instante ISO; "hasta" incluye el día completo. */
function dayStart(day: string, next = false) {
  if (!day) return undefined;
  const d = new Date(`${day}T00:00`);
  if (next) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

function summary(e: AuditEvent): string | null {
  const d = e.detail ?? {};
  if (e.action === "auth.login_failed") return REASON_LABEL[String(d.reason)] ? t(REASON_LABEL[String(d.reason)]) : String(d.reason ?? "");
  if (e.action === "auth.locked" && d.until) {
    const scope = d.scope === "account" ? `${t("desde varias IP")} · ` : d.scope === "pair" ? `${t("desde esta IP")} · ` : "";
    return `${scope}${t("hasta {date}", { date: when(String(d.until)) })}`;
  }
  if (e.action === "auth.ip_blocked" && d.until) return t("hasta {date}", { date: when(String(d.until)) });
  if (e.action === "survey.submitted") {
    const score = d.score === null || d.score === undefined ? "" : ` · ${t("{n} puntos", { n: String(d.score) })}`;
    return `${d.survey ?? d.surveyId}${score}`;
  }
  if (e.action === "audit.exported") return t("{n} filas", { n: Number(d.rows) });
  if (e.action === "mentions.geolocated") return t("{n} menciones revisadas", { n: Number(d.reviewed) });
  if (e.action.startsWith("target.") && d.reason) return t("motivo: {reason}", { reason: String(d.reason) });
  if (d.passwordReset) return t("contraseña restablecida");
  return null;
}

/** Bitácora: quién hizo qué, cuándo y desde dónde. Solo para administradores. */
export function AuditDialog({ onClose }: { onClose: () => void }) {
  const [actions, setActions] = useState<Record<string, string>>({});
  const [form, setForm] = useState({ action: "", actor: "", q: "", since: "", until: "", failedOnly: false });
  const [filters, setFilters] = useState<AuditFilters>({});
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { tApi } = useI18n();

  async function load(f: AuditFilters, before?: number) {
    setError(null);
    try {
      const page = await api.audit(f, before);
      setActions(page.actions);
      setEvents((prev) => (before && prev ? [...prev, ...page.events] : page.events));
      setNext(page.nextBefore);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  useEffect(() => { load({}); }, []);

  function apply(e?: React.FormEvent) {
    e?.preventDefault();
    const f: AuditFilters = {
      action: form.action || undefined, actor: form.actor.trim() || undefined, q: form.q.trim() || undefined,
      since: dayStart(form.since), until: dayStart(form.until, true), success: form.failedOnly ? false : undefined,
    };
    setFilters(f);
    setOpen(null);
    load(f);
  }

  function clear() {
    setForm({ action: "", actor: "", q: "", since: "", until: "", failedOnly: false });
    setFilters({});
    setOpen(null);
    load({});
  }

  return (
    <Modal title={t("Auditoría")} onClose={onClose} wide>
      <form className="audit-filters" onSubmit={apply}>
        <select value={form.action} aria-label={t("Acción")} onChange={(e) => setForm({ ...form, action: e.target.value })}>
          <option value="">{t("Todas las acciones")}</option>
          {GROUPS.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
          {Object.entries(actions).map(([v, l]) => <option key={v} value={v}>{tApi(l)}</option>)}
        </select>
        <input placeholder={t("Usuario (correo)")} value={form.actor} onChange={(e) => setForm({ ...form, actor: e.target.value })} />
        <input placeholder={t("Buscar objeto o IP")} value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} />
        <label>{t("Desde")}<input type="date" value={form.since} onChange={(e) => setForm({ ...form, since: e.target.value })} /></label>
        <label>{t("Hasta")}<input type="date" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} /></label>
        <label className="check">
          <input type="checkbox" checked={form.failedOnly} onChange={(e) => setForm({ ...form, failedOnly: e.target.checked })} />
          {t("Solo fallidos")}
        </label>
        <div className="actions">
          <button type="submit">{t("Filtrar")}</button>
          <button type="button" className="ghost" onClick={clear}>{t("Limpiar")}</button>
          <a className="button ghost" href={auditCsvUrl(filters)} download>{t("Descargar CSV")}</a>
        </div>
      </form>

      {error && <p className="error" role="alert">{error}</p>}
      {!events ? <div className="empty">{t("Cargando…")}</div> : !events.length ? <div className="empty">{t("Sin eventos con esos filtros.")}</div> : (
        <table className="audit">
          <thead><tr><th>{t("Fecha")}</th><th>{t("Usuario")}</th><th>{t("Acción")}</th><th>{t("Afectado")}</th><th>IP</th></tr></thead>
          <tbody>
            {events.map((e) => {
              const extra = summary(e);
              const details = !!e.changes || !!e.userAgent;
              return (
                <Fragment key={e.id}>
                  <tr className={`${e.success ? "" : "failed"} ${details ? "clickable" : ""}`}
                    onClick={() => details && setOpen(open === e.id ? null : e.id)} aria-expanded={details ? open === e.id : undefined}>
                    <td className="muted when">{when(e.at)}</td>
                    <td className="who">
                      {e.actorEmail ?? "—"}
                      {e.actorRole && <span className="muted"> · {t(ROLE_LABEL[e.actorRole])}</span>}
                    </td>
                    <td className="what">
                      <span className={e.success ? "" : "error"}>{tApi(e.actionLabel)}</span>
                      {extra && <span className="muted"> · {extra}</span>}
                      {e.changes && <span className="muted"> · {t("{n} cambio(s)", { n: Object.keys(e.changes).length })} {open === e.id ? "▴" : "▾"}</span>}
                    </td>
                    <td className="target">{e.entityLabel ?? "—"}</td>
                    <td className="muted ip" data-label="IP">{e.ip ?? "—"}</td>
                  </tr>
                  {open === e.id && (
                    <tr className="audit-detail">
                      <td colSpan={5}>
                        {e.changes && (
                          <table className="changes">
                            <thead><tr><th>{t("Campo")}</th><th>{t("Antes")}</th><th>{t("Después")}</th></tr></thead>
                            <tbody>
                              {Object.entries(e.changes).map(([field, [before, after]]) => (
                                <tr key={field}>
                                  <td>{FIELD_LABEL[field] ? t(FIELD_LABEL[field]) : field}</td>
                                  <td className="before">{show(field, before)}</td>
                                  <td className="after">{show(field, after)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                        {e.userAgent && <p className="muted ua">{t("Navegador:")} {e.userAgent}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {next && <button type="button" className="ghost more" onClick={() => load(filters, next)}>{t("Cargar más")}</button>}
      <p className="muted" style={{ fontSize: 12 }}>
        {t("Se registran inicios y cierres de sesión (también los fallidos), cambios de contraseña, cuentas y roles, objetivos y cuestionarios, con los valores de antes y después. Las contraseñas nunca se guardan. La bitácora no se puede editar ni borrar desde minOS.")}
      </p>
    </Modal>
  );
}
