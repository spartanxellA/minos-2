"use client";

import { useState } from "react";
import { api, type MatchStatus, type Screening, type ScreeningMatch, type Target } from "@/lib/api";
import { Modal } from "./AccountDialogs";

const date = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("es-MX", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

export const SCREENING_STATE: Record<Screening["status"], { label: string; className: string }> = {
  not_screened: { label: "Sin revisar todavía", className: "muted" },
  clear: { label: "Sin coincidencias", className: "ok" },
  possible: { label: "Posible coincidencia", className: "warn" },
  confirmed: { label: "Coincidencia confirmada", className: "error" },
};

const MATCH_STATUS: Record<MatchStatus, string> = { pending: "Pendiente", confirmed: "Confirmada", dismissed: "Descartada" };

/** Resultado de la revisión del objetivo en listas negras (sanciones, SAT, inhabilitados, PEP). */
export function ScreeningCard({ target, screening, canReview, onTargetSaved, onChanged }: {
  target: Target;
  screening: Screening | null;
  canReview: boolean;
  onTargetSaved: (t: Target) => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const state = screening ? SCREENING_STATE[screening.status] : null;
  const active = screening?.matches.filter((m) => m.active && m.status !== "dismissed") ?? [];

  return (
    <section className="card span-3">
      <h2>Listas negras</h2>
      {!screening ? <div className="empty">Cargando…</div> : (
        <>
          <p><span className={`pill-state ${state!.className}`}>{state!.label}</span></p>
          {target.kind === "Country" ? (
            <p className="muted" style={{ fontSize: 12 }}>Los países no se revisan en listas de personas y empresas.</p>
          ) : (
            <>
              <div className="drivers">
                <span>Pendientes de revisar</span><b>{screening.pending}</b>
                <span>Confirmadas</span><b>{screening.confirmed}</b>
                <span>Listas consultadas</span><b>{screening.lists}</b>
                <span>Última revisión</span><b>{screening.screenedAt ? date(screening.screenedAt) : "—"}</b>
              </div>
              {active.slice(0, 3).map((m) => (
                <div key={m.id} className={`hit ${m.status}`}>
                  <b>{m.listedName}</b> · {m.sourceName}
                  <div className="muted">{Math.round(m.score)} % · {MATCH_STATUS[m.status]}</div>
                </div>
              ))}
            </>
          )}
          <button type="button" className="ghost" style={{ marginTop: 8 }} onClick={() => setOpen(true)}>
            {active.length ? "Ver y revisar" : "Ver detalle"}
          </button>
        </>
      )}
      {open && screening && (
        <ScreeningDialog target={target} screening={screening} canReview={canReview} onClose={() => setOpen(false)}
          onTargetSaved={onTargetSaved} onChanged={onChanged} />
      )}
    </section>
  );
}

function ScreeningDialog({ target, screening, canReview, onClose, onTargetSaved, onChanged }: {
  target: Target;
  screening: Screening;
  canReview: boolean;
  onClose: () => void;
  onTargetSaved: (t: Target) => void;
  onChanged: () => void;
}) {
  const [showDismissed, setShowDismissed] = useState(false);
  const shown = screening.matches.filter((m) => showDismissed || m.status !== "dismissed");
  const dismissed = screening.matches.length - screening.matches.filter((m) => m.status !== "dismissed").length;

  return (
    <Modal title={`Listas negras · ${target.name}`} onClose={onClose} wide>
      <p className="disclaimer">{screening.disclaimer}</p>
      {target.kind !== "Country" && <IdentityForm target={target} canEdit={canReview} onSaved={onTargetSaved} />}
      <h3>Coincidencias</h3>
      {shown.length === 0 ? (
        <p className="muted">
          {screening.status === "not_screened"
            ? "Todavía no se revisa. Se revisa sola en menos de un minuto al crear o editar el objetivo."
            : "Sin coincidencias en las listas cargadas."}
        </p>
      ) : shown.map((m) => <MatchItem key={m.id} match={m} canReview={canReview} onChanged={onChanged} />)}
      {dismissed > 0 && (
        <button type="button" className="ghost" onClick={() => setShowDismissed(!showDismissed)}>
          {showDismissed ? "Ocultar descartadas" : `Ver descartadas (${dismissed})`}
        </button>
      )}
    </Modal>
  );
}

export function MatchItem({ match: m, canReview, onChanged, showTarget }: {
  match: ScreeningMatch;
  canReview: boolean;
  onChanged: () => void;
  showTarget?: boolean;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const e = m.entry;

  async function decide(decision: MatchStatus) {
    setBusy(true);
    setError(null);
    try {
      await api.reviewMatch(m.id, decision, note);
      setNote("");
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const facts: [string, string | undefined][] = [
    ["Tipo de lista", m.categoryLabel],
    ["Alias", e.aliases?.slice(0, 6).join(" · ")],
    ["Nacimiento", e.birthDates?.join(", ")],
    ["Nacionalidad", e.nationalities?.join(", ")],
    ["Documentos", e.identifiers?.join(", ")],
    ["Programa o cargo", e.programs?.join(" · ")],
    ["Situación", e.status ?? undefined],
    ["En la lista desde", e.listedOn ?? undefined],
  ];

  return (
    <article className={`match ${m.status} ${m.active ? "" : "retired"}`}>
      <header>
        <div>
          {showTarget && m.targetName && <div className="muted" style={{ fontSize: 12 }}>{m.targetName}</div>}
          <b>{m.listedName}</b> <span className="muted">· {m.sourceName}</span>
        </div>
        <div className="score">
          <span className={`tag ${m.strength === "strong" ? "severe" : ""}`}>{m.strength === "strong" ? "Fuerte" : "Posible"}</span>
          <b>{Math.round(m.score)} %</b>
        </div>
      </header>
      <ul className="reasons">{m.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <dl>
        {facts.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
      {e.url && <a href={e.url} target="_blank" rel="noreferrer">Ver en la fuente oficial ↗</a>}
      <div className="review">
        <span className={`state ${m.status}`}>{MATCH_STATUS[m.status]}{!m.active && " · ya no aparece en la lista"}</span>
        {m.reviewedAt && <span className="muted"> · {m.reviewedByEmail} · {date(m.reviewedAt)}</span>}
        {m.reviewNote && <p className="note">“{m.reviewNote}”</p>}
      </div>
      {canReview && m.active && (
        <div className="decide">
          <input aria-label="Nota de la revisión" placeholder="Nota obligatoria: por qué es o no es la misma persona"
            value={note} onChange={(ev) => setNote(ev.target.value)} />
          {m.status !== "confirmed" && <button type="button" disabled={busy} onClick={() => decide("confirmed")}>Confirmar</button>}
          {m.status !== "dismissed" && <button type="button" className="ghost" disabled={busy} onClick={() => decide("dismissed")}>Descartar</button>}
          {m.status !== "pending" && <button type="button" className="ghost" disabled={busy} onClick={() => decide("pending")}>Volver a pendiente</button>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </article>
  );
}

/** Fecha de nacimiento, nacionalidad y documentos: bajan mucho los falsos positivos. */
function IdentityForm({ target, canEdit, onSaved }: { target: Target; canEdit: boolean; onSaved: (t: Target) => void }) {
  const person = target.kind === "Person";
  const [birth, setBirth] = useState(target.birthDate ?? "");
  const [nationality, setNationality] = useState(target.nationality ?? "");
  const [ids, setIds] = useState<Record<string, string>>({ rfc: "", curp: "", pasaporte: "", ...target.identifiers });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const keys = person ? ["rfc", "curp", "pasaporte"] : ["rfc"];

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    try {
      const saved = await api.updateTarget({
        ...target, birthDate: person && birth.trim() ? birth.trim() : null, nationality: nationality.trim() || null,
        identifiers: Object.fromEntries(Object.entries(ids).filter(([, v]) => v.trim())),
      });
      onSaved(saved);
      setMessage({ ok: true, text: "Guardado. Se vuelve a revisar en menos de un minuto." });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <form className="identity" onSubmit={save}>
      <p className="muted" style={{ margin: 0, fontSize: 12 }}>
        Datos para distinguir homónimos. Un RFC o CURP igual confirma casi seguro; una fecha de nacimiento distinta descarta.
      </p>
      <div className="fields">
        {person && (
          <label>Fecha de nacimiento
            <input disabled={!canEdit} placeholder="AAAA-MM-DD o AAAA" pattern="\d{4}(-\d{2}-\d{2})?" value={birth}
              onChange={(e) => setBirth(e.target.value)} />
          </label>
        )}
        <label>{person ? "Nacionalidad" : "País"}
          <input disabled={!canEdit} placeholder="México" value={nationality} onChange={(e) => setNationality(e.target.value)} />
        </label>
        {keys.map((k) => (
          <label key={k}>{k.toUpperCase()}
            <input disabled={!canEdit} value={ids[k] ?? ""} onChange={(e) => setIds({ ...ids, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {canEdit && <button type="submit">Guardar datos</button>}
      {message && <span className={message.ok ? "ok" : "error"} role="status"> {message.text}</span>}
    </form>
  );
}
