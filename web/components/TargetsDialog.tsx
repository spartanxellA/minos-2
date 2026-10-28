"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { api, can, KIND_LABEL, SOURCE_LABEL, type Me, type Target, type TargetKind } from "@/lib/api";
import { Modal } from "./AccountDialogs";

type Filter = "active" | "inactive" | "all";
const FILTERS: [Filter, string][] = [["active", "Activos"], ["inactive", "Dados de baja"], ["all", "Todos"]];
const HANDLE_KEYS = ["x", "youtube", "facebook", "instagram", "bluesky", "reddit"];
const ID_KEYS: Record<string, string> = { rfc: "RFC", curp: "CURP", pasaporte: "Pasaporte" };

const date = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString("es-MX", { dateStyle: "medium" }) : "—");
const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const fold = (s: string) => s.normalize("NFD").replace(/\p{Mn}/gu, "").toLowerCase();

/** Mantenimiento de objetivos: cambios, baja (con motivo), reactivación y, para administradores, borrado definitivo. */
export function TargetsDialog({ user, onClose, onChanged }: {
  user: Me; onClose: () => void; onChanged: (t: Target | { id: string; deleted: true }) => void;
}) {
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [filter, setFilter] = useState<Filter>("active");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Target | null>(null);
  const [leaving, setLeaving] = useState<Target | null>(null);
  const [error, setError] = useState<string | null>(null);
  const analyst = can(user, "analyst");
  const admin = can(user, "admin");

  const load = () => api.targets().then(setTargets).catch((err) => setError((err as Error).message));
  useEffect(() => { load(); }, []);

  const counts = useMemo(() => ({
    active: targets?.filter((t) => t.enabled).length ?? 0,
    inactive: targets?.filter((t) => !t.enabled).length ?? 0,
    all: targets?.length ?? 0,
  }), [targets]);
  const shown = useMemo(() => (targets ?? []).filter((t) =>
    (filter === "all" || t.enabled === (filter === "active")) &&
    (!q.trim() || fold([t.name, ...t.aliases, ...Object.values(t.identifiers ?? {})].join(" ")).includes(fold(q.trim())))
  ), [targets, filter, q]);

  function saved(t: Target) {
    setTargets((p) => p?.map((x) => (x.id === t.id ? t : x)) ?? null);
    onChanged(t);
  }

  async function run(action: () => Promise<Target | void>, id: string) {
    setError(null);
    try {
      const t = await action();
      if (t) saved(t);
      else {
        setTargets((p) => p?.filter((x) => x.id !== id) ?? null);
        onChanged({ id, deleted: true });
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function remove(t: Target) {
    const typed = window.prompt(
      `Esto borra para siempre a «${t.name}» con sus menciones, gráficas, cuestionarios y coincidencias. ` +
      "La bitácora conserva el registro. Escribe el nombre para confirmar:");
    if (typed === null) return;
    if (typed.trim().toLowerCase() !== t.name.toLowerCase()) return setError("El nombre no coincide; no se borró.");
    run(() => api.deleteTarget(t.id), t.id);
  }

  if (editing) {
    return (
      <Modal title={`Editar · ${editing.name}`} onClose={onClose} wide>
        <TargetEditor target={editing} onCancel={() => setEditing(null)} onSaved={(t) => { saved(t); setEditing(null); }} />
      </Modal>
    );
  }

  return (
    <Modal title="Objetivos" onClose={onClose} wide>
      <div className="targets-bar">
        <div className="segmented" role="tablist">
          {FILTERS.map(([f, label]) => (
            <button key={f} type="button" role="tab" aria-selected={filter === f} className={filter === f ? "" : "ghost"}
              onClick={() => setFilter(f)}>{label} <span className="count">{counts[f]}</span></button>
          ))}
        </div>
        <input type="search" placeholder="Buscar nombre, alias o RFC" aria-label="Buscar" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!targets ? <div className="empty">Cargando…</div> : !shown.length ? (
        <div className="empty">{filter === "inactive" ? "No hay objetivos dados de baja." : "Sin objetivos con ese filtro."}</div>
      ) : (
        <table className="targets">
          <thead><tr><th>Objetivo</th><th>Tipo</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {shown.map((t) => (
              <Fragment key={t.id}>
              <tr className={t.enabled ? "" : "inactive"}>
                <td className="name">
                  <b>{t.name}</b>
                  {t.aliases.length > 0 && <div className="muted">{t.aliases.join(", ")}</div>}
                  <div className="muted small">Alta {date(t.createdAt)}{t.updatedAt && ` · cambio ${date(t.updatedAt)}`}</div>
                </td>
                <td className="kind">{KIND_LABEL[t.kind]}</td>
                <td className="state">
                  {t.enabled ? <span className="tag positive">Activo</span> : (
                    <>
                      <span className="tag">De baja</span>
                      <div className="muted small">{date(t.deactivatedAt)}{t.deactivatedByEmail && ` · ${t.deactivatedByEmail}`}</div>
                      {t.deactivationReason && <div className="note">“{t.deactivationReason}”</div>}
                    </>
                  )}
                </td>
                <td className="actions">
                  {analyst && <button type="button" className="ghost" onClick={() => setEditing(t)}>Editar</button>}
                  {analyst && t.enabled && (
                    <button type="button" className="ghost danger" onClick={() => setLeaving(leaving?.id === t.id ? null : t)}>Dar de baja</button>
                  )}
                  {analyst && !t.enabled && (
                    <button type="button" className="ghost" onClick={() => run(() => api.reactivateTarget(t.id), t.id)}>Reactivar</button>
                  )}
                  {admin && !t.enabled && <button type="button" className="ghost danger" onClick={() => remove(t)}>Borrar</button>}
                </td>
              </tr>
              {leaving?.id === t.id && (
                <tr className="leave">
                  <td colSpan={4}>
                    <DeactivateForm target={t} onCancel={() => setLeaving(null)}
                      onDone={(x) => { saved(x); setLeaving(null); }} />
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small" style={{ marginTop: 12 }}>
        Dar de baja detiene la búsqueda en fuentes, el cálculo del índice y la revisión en listas, pero conserva toda su
        historia; se puede reactivar cuando quieras. {admin ? "Solo los dados de baja se pueden borrar definitivamente." : ""}
        {!analyst && " Los cambios los hace un analista o administrador."}
      </p>
    </Modal>
  );
}

function DeactivateForm({ target, onCancel, onDone }: { target: Target; onCancel: () => void; onDone: (t: Target) => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      onDone(await api.deactivateTarget(target.id, reason));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <form className="deactivate" onSubmit={submit}>
      <input autoFocus required minLength={3} aria-label="Motivo de la baja" placeholder="Motivo de la baja (queda en la bitácora)"
        value={reason} onChange={(e) => setReason(e.target.value)} />
      <button type="submit" className="danger">Dar de baja</button>
      <button type="button" className="ghost" onClick={onCancel}>Cancelar</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

/** Todos los datos del objetivo. Cambiar nombre, alias, tipo o documentos repite la búsqueda y la revisión en listas. */
export function TargetEditor({ target, onSaved, onCancel }: { target: Target; onSaved: (t: Target) => void; onCancel: () => void }) {
  const [name, setName] = useState(target.name);
  const [kind, setKind] = useState<TargetKind>(target.kind);
  const [aliases, setAliases] = useState(target.aliases.join(", "));
  const [keywords, setKeywords] = useState(target.keywords.join(", "));
  const [excluded, setExcluded] = useState(target.excludedTerms.join(", "));
  const [handles, setHandles] = useState<Record<string, string>>({ ...target.handles });
  const [birth, setBirth] = useState(target.birthDate ?? "");
  const [nationality, setNationality] = useState(target.nationality ?? "");
  const [ids, setIds] = useState<Record<string, string>>({ ...target.identifiers });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const person = kind === "Person";
  const idKeys = person ? Object.keys(ID_KEYS) : ["rfc"];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.updateTarget({
        id: target.id, name, kind, aliases: split(aliases), keywords: split(keywords), excludedTerms: split(excluded),
        handles: Object.fromEntries(Object.entries(handles).filter(([, v]) => v.trim())),
        birthDate: person && birth.trim() ? birth.trim() : null, nationality: nationality.trim() || null,
        identifiers: Object.fromEntries(Object.entries(ids).filter(([k, v]) => idKeys.includes(k) && v.trim())),
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="target-editor" onSubmit={submit}>
      {!target.enabled && <p className="notice">Este objetivo está dado de baja; puedes corregir sus datos sin reactivarlo.</p>}
      <fieldset>
        <legend>Identificación</legend>
        <label className="wide">Nombre<input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Tipo
          <select value={kind} onChange={(e) => setKind(e.target.value as TargetKind)}>
            {Object.entries(KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
      </fieldset>
      <fieldset>
        <legend>Búsqueda en fuentes</legend>
        <label className="wide">Alias, siglas o apodos <small>separados por coma</small>
          <input value={aliases} onChange={(e) => setAliases(e.target.value)} /></label>
        <label className="wide">Palabras clave <small>cargo, empresa, ciudad</small>
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)} /></label>
        <label className="wide">Excluir <small>homónimos u otros contextos</small>
          <input value={excluded} onChange={(e) => setExcluded(e.target.value)} /></label>
        {HANDLE_KEYS.map((k) => (
          <label key={k}>Cuenta en {SOURCE_LABEL[k] ?? k}
            <input placeholder={k === "x" ? "@cuenta" : "cuenta o id"} value={handles[k] ?? ""}
              onChange={(e) => setHandles({ ...handles, [k]: e.target.value })} /></label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Listas negras</legend>
        {person && (
          <label>Fecha de nacimiento
            <input placeholder="AAAA-MM-DD o AAAA" pattern="\d{4}(-\d{2}-\d{2})?" value={birth} onChange={(e) => setBirth(e.target.value)} />
          </label>
        )}
        <label>Nacionalidad<input maxLength={64} value={nationality} onChange={(e) => setNationality(e.target.value)} /></label>
        {idKeys.map((k) => (
          <label key={k}>{ID_KEYS[k]}<input value={ids[k] ?? ""} onChange={(e) => setIds({ ...ids, [k]: e.target.value })} /></label>
        ))}
      </fieldset>
      <p className="muted small">
        Al cambiar el nombre, los alias, el tipo o los documentos se vuelve a buscar en las fuentes y a revisar en las
        listas en menos de un minuto. Las menciones ya guardadas se conservan. Cada cambio queda en la bitácora.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Guardando…" : "Guardar cambios"}</button>
        <button type="button" className="ghost" onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  );
}
