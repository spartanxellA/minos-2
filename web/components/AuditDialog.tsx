"use client";

import { Fragment, useEffect, useState } from "react";
import { api, auditCsvUrl, KIND_LABEL, ROLE_LABEL, type AuditEvent, type AuditFilters, type Role, type TargetKind } from "@/lib/api";
import { Modal } from "./AccountDialogs";

const FIELD_LABEL: Record<string, string> = {
  name: "Nombre", email: "Correo", role: "Rol", active: "Activa", kind: "Tipo", aliases: "Alias",
  keywords: "Palabras clave", excludedTerms: "Términos excluidos", handles: "Cuentas", enabled: "Activo",
  birthDate: "Fecha de nacimiento", nationality: "Nacionalidad", identifiers: "Documentos",
};
const REASON_LABEL: Record<string, string> = {
  wrong_password: "contraseña incorrecta", unknown_account: "correo sin cuenta", inactive: "cuenta desactivada",
  locked: "cuenta bloqueada",
};
const GROUPS: [string, string][] = [
  ["auth.", "Sesiones (todas)"], ["user.", "Cuentas (todas)"], ["target.", "Objetivos (todos)"],
];

function show(field: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "sí" : "no";
  if (field === "role") return ROLE_LABEL[value as Role] ?? String(value);
  if (field === "kind") return KIND_LABEL[value as TargetKind] ?? String(value);
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? entries.map(([k, v]) => `${k}: ${v}`).join(", ") : "—";
  }
  return String(value);
}

const when = (iso: string) => new Date(iso).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "medium" });

/** Fecha del calendario (día local) → instante ISO; "hasta" incluye el día completo. */
function dayStart(day: string, next = false) {
  if (!day) return undefined;
  const d = new Date(`${day}T00:00`);
  if (next) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

function summary(e: AuditEvent): string | null {
  const d = e.detail ?? {};
  if (e.action === "auth.login_failed") return REASON_LABEL[String(d.reason)] ?? String(d.reason ?? "");
  if (e.action === "auth.locked" && d.until) return `hasta ${when(String(d.until))}`;
  if (e.action === "survey.submitted") {
    const score = d.score === null || d.score === undefined ? "" : ` · ${d.score} puntos`;
    return `${d.survey ?? d.surveyId}${score}`;
  }
  if (e.action === "audit.exported") return `${d.rows} filas`;
  if (e.action.startsWith("target.") && d.reason) return `motivo: ${d.reason}`;
  if (d.passwordReset) return "contraseña restablecida";
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
    <Modal title="Auditoría" onClose={onClose} wide>
      <form className="audit-filters" onSubmit={apply}>
        <select value={form.action} aria-label="Acción" onChange={(e) => setForm({ ...form, action: e.target.value })}>
          <option value="">Todas las acciones</option>
          {GROUPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          {Object.entries(actions).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input placeholder="Usuario (correo)" value={form.actor} onChange={(e) => setForm({ ...form, actor: e.target.value })} />
        <input placeholder="Buscar objeto o IP" value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} />
        <label>Desde<input type="date" value={form.since} onChange={(e) => setForm({ ...form, since: e.target.value })} /></label>
        <label>Hasta<input type="date" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} /></label>
        <label className="check">
          <input type="checkbox" checked={form.failedOnly} onChange={(e) => setForm({ ...form, failedOnly: e.target.checked })} />
          Solo fallidos
        </label>
        <div className="actions">
          <button type="submit">Filtrar</button>
          <button type="button" className="ghost" onClick={clear}>Limpiar</button>
          <a className="button ghost" href={auditCsvUrl(filters)} download>Descargar CSV</a>
        </div>
      </form>

      {error && <p className="error" role="alert">{error}</p>}
      {!events ? <div className="empty">Cargando…</div> : !events.length ? <div className="empty">Sin eventos con esos filtros.</div> : (
        <table className="audit">
          <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Afectado</th><th>IP</th></tr></thead>
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
                      {e.actorRole && <span className="muted"> · {ROLE_LABEL[e.actorRole]}</span>}
                    </td>
                    <td className="what">
                      <span className={e.success ? "" : "error"}>{e.actionLabel}</span>
                      {extra && <span className="muted"> · {extra}</span>}
                      {e.changes && <span className="muted"> · {Object.keys(e.changes).length} cambio(s) {open === e.id ? "▴" : "▾"}</span>}
                    </td>
                    <td className="target">{e.entityLabel ?? "—"}</td>
                    <td className="muted ip" data-label="IP">{e.ip ?? "—"}</td>
                  </tr>
                  {open === e.id && (
                    <tr className="audit-detail">
                      <td colSpan={5}>
                        {e.changes && (
                          <table className="changes">
                            <thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead>
                            <tbody>
                              {Object.entries(e.changes).map(([field, [before, after]]) => (
                                <tr key={field}>
                                  <td>{FIELD_LABEL[field] ?? field}</td>
                                  <td className="before">{show(field, before)}</td>
                                  <td className="after">{show(field, after)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                        {e.userAgent && <p className="muted ua">Navegador: {e.userAgent}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {next && <button type="button" className="ghost more" onClick={() => load(filters, next)}>Cargar más</button>}
      <p className="muted" style={{ fontSize: 12 }}>
        Se registran inicios y cierres de sesión (también los fallidos), cambios de contraseña, cuentas y roles, objetivos y
        cuestionarios, con los valores de antes y después. Las contraseñas nunca se guardan. La bitácora no se puede editar ni borrar
        desde minOS.
      </p>
    </Modal>
  );
}
