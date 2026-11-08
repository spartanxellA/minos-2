"use client";

import { useState } from "react";
import { api, type EntryChange, type MatchStatus, type Screening, type ScreeningMatch, type Target } from "@/lib/api";
import { Modal } from "./AccountDialogs";
import { locale, msg, useI18n } from "@/lib/i18n";

const date = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(locale(), { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

export const SCREENING_STATE: Record<Screening["status"], { label: string; className: string }> = {
  not_screened: { label: msg("Sin revisar todavía"), className: "muted" },
  clear: { label: msg("Sin coincidencias"), className: "ok" },
  possible: { label: msg("Posible coincidencia"), className: "warn" },
  confirmed: { label: msg("Coincidencia confirmada"), className: "error" },
};

const MATCH_STATUS: Record<MatchStatus, string> = { pending: msg("Pendiente"), confirmed: msg("Confirmada"), dismissed: msg("Descartada") };

/** Resultado de la revisión del objetivo en listas negras (sanciones, SAT, inhabilitados, PEP). */
export function ScreeningCard({ target, screening, canReview, onTargetSaved, onChanged }: {
  target: Target;
  screening: Screening | null;
  canReview: boolean;
  onTargetSaved: (t: Target) => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const state = screening ? SCREENING_STATE[screening.status] : null;
  const active = screening?.matches.filter((m) => m.active && m.status !== "dismissed") ?? [];

  return (
    <section className="card span-3">
      <h2>{t("Listas negras")}</h2>
      {!screening ? <div className="empty">{t("Cargando…")}</div> : (
        <>
          <p><span className={`pill-state ${state!.className}`}>{t(state!.label)}</span></p>
          {target.kind === "Country" ? (
            <p className="muted" style={{ fontSize: 12 }}>{t("Los países no se revisan en listas de personas y empresas.")}</p>
          ) : (
            <>
              <div className="drivers">
                <span>{t("Pendientes de revisar")}</span><b>{screening.pending}</b>
                <span>{t("Confirmadas")}</span><b>{screening.confirmed}</b>
                <span>{t("Listas consultadas")}</span><b>{screening.lists}</b>
                <span>{t("Última revisión")}</span><b>{screening.screenedAt ? date(screening.screenedAt) : "—"}</b>
              </div>
              {active.slice(0, 3).map((m) => (
                <div key={m.id} className={`hit ${m.status}`}>
                  <b>{m.listedName}</b> · {m.sourceName}
                  <div className="muted">{Math.round(m.score)} % · {t(MATCH_STATUS[m.status])}</div>
                </div>
              ))}
            </>
          )}
          <button type="button" className="ghost" style={{ marginTop: 8 }} onClick={() => setOpen(true)}>
            {active.length ? t("Ver y revisar") : t("Ver detalle")}
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
  const { t, tApi } = useI18n();
  const shown = screening.matches.filter((m) => showDismissed || m.status !== "dismissed");
  const dismissed = screening.matches.length - screening.matches.filter((m) => m.status !== "dismissed").length;

  return (
    <Modal title={`${t("Listas negras")} · ${target.name}`} onClose={onClose} wide>
      <p className="disclaimer">{tApi(screening.disclaimer)}</p>
      {target.kind !== "Country" && <IdentityForm target={target} canEdit={canReview} onSaved={onTargetSaved} />}
      <h3>{t("Coincidencias")}</h3>
      {shown.length === 0 ? (
        <p className="muted">
          {screening.status === "not_screened"
            ? t("Todavía no se revisa. Se revisa sola en menos de un minuto al crear o editar el objetivo.")
            : t("Sin coincidencias en las listas cargadas.")}
        </p>
      ) : shown.map((m) => <MatchItem key={m.id} match={m} canReview={canReview} onChanged={onChanged} />)}
      {dismissed > 0 && (
        <button type="button" className="ghost" onClick={() => setShowDismissed(!showDismissed)}>
          {showDismissed ? t("Ocultar descartadas") : t("Ver descartadas ({n})", { n: dismissed })}
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
  const { t, tApi } = useI18n();
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
    [t("Tipo de lista"), tApi(m.categoryLabel)],
    [t("Alias"), e.aliases?.slice(0, 6).join(" · ")],
    [t("Nacimiento"), e.birthDates?.join(", ")],
    [t("Nacionalidad"), e.nationalities?.join(", ")],
    [t("Documentos"), e.identifiers?.join(", ")],
    [t("Programa o cargo"), e.programs?.join(" · ")],
    [t("Situación"), e.status ?? undefined],
    [t("En la lista desde"), e.listedOn ?? undefined],
  ];

  return (
    <article className={`match ${m.status} ${m.active ? "" : "retired"}`}>
      <header>
        <div>
          {showTarget && m.targetName && <div className="muted" style={{ fontSize: 12 }}>{m.targetName}</div>}
          <b>{m.listedName}</b> <span className="muted">· {m.sourceName}</span>
        </div>
        <div className="score">
          <span className={`tag ${m.strength === "strong" ? "severe" : ""}`}>{m.strength === "strong" ? t("Fuerte") : t("Posible")}</span>
          <b>{Math.round(m.score)} %</b>
        </div>
      </header>
      <ul className="reasons">{m.reasons.map((r) => <li key={r}>{tApi(r)}</li>)}</ul>
      <dl>
        {facts.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
      {e.url && <a href={e.url} target="_blank" rel="noreferrer">{t("Ver en la fuente oficial ↗")}</a>}
      <EntryHistory matchId={m.id} />
      <div className="review">
        <span className={`state ${m.status}`}>{t(MATCH_STATUS[m.status])}{!m.active && ` · ${t("ya no aparece en la lista")}`}</span>
        {m.reviewedAt && <span className="muted"> · {m.reviewedByEmail} · {date(m.reviewedAt)}</span>}
        {m.reviewNote && <p className="note">“{m.reviewNote}”</p>}
      </div>
      {canReview && m.active && (
        <div className="decide">
          <input aria-label={t("Nota de la revisión")} placeholder={t("Nota obligatoria: por qué es o no es la misma persona")}
            value={note} onChange={(ev) => setNote(ev.target.value)} />
          {m.status !== "confirmed" && <button type="button" disabled={busy} onClick={() => decide("confirmed")}>{t("Confirmar")}</button>}
          {m.status !== "dismissed" && <button type="button" className="ghost" disabled={busy} onClick={() => decide("dismissed")}>{t("Descartar")}</button>}
          {m.status !== "pending" && <button type="button" className="ghost" disabled={busy} onClick={() => decide("pending")}>{t("Volver a pendiente")}</button>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </article>
  );
}

const CHANGE_LABEL: Record<EntryChange["change"], string> = {
  added: msg("Alta en la lista"), status: msg("Cambio de estatus"), changed: msg("Cambio de datos"), removed: msg("Salió de la lista"),
};
const FIELD_LABEL: Record<string, string> = {
  status: msg("Estatus"), name: msg("Nombre"), programs: msg("Cargo"), birth_dates: msg("Nacimiento"), identifiers: msg("Documentos"),
  nationalities: msg("País"), aliases: msg("Alias"),
};
const plain = (v: unknown) => (v == null || (Array.isArray(v) && !v.length) ? "—" : Array.isArray(v) ? v.join(" · ") : String(v));

/** Cambios del registro en las cargas de la lista (p. ej. cuándo pasó de Activo a Inactivo). */
function EntryHistory({ matchId }: { matchId: number }) {
  const [items, setItems] = useState<EntryChange[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  async function toggle() {
    setOpen(!open);
    if (!items && !open) {
      api.matchHistory(matchId).then(setItems).catch((err) => setError((err as Error).message));
    }
  }

  return (
    <div className="entry-history">
      <button type="button" className="link" onClick={toggle} aria-expanded={open}>
        {open ? t("Ocultar historial en la lista") : t("Historial en la lista")}
      </button>
      {open && (error ? <p className="error">{error}</p> : !items ? <p className="muted">{t("Cargando…")}</p> : items.length === 0 ? (
        <p className="muted">{t("Sin cambios registrados desde que se cargó la lista.")}</p>
      ) : (
        <ol>
          {items.map((h, i) => (
            <li key={i}>
              <b>{date(h.at)}</b> · {t(CHANGE_LABEL[h.change])}
              {h.fileName && <span className="muted"> · {h.fileName}</span>}
              {Object.entries(h.fields).filter(([, [a, b]]) => h.change !== "added" || b != null).map(([f, [a, b]]) => (
                <div key={f} className="muted">{FIELD_LABEL[f] ? t(FIELD_LABEL[f]) : f}: {h.change === "added" ? plain(b) : <>{plain(a)} → {plain(b)}</>}</div>
              ))}
            </li>
          ))}
        </ol>
      ))}
    </div>
  );
}

/** Fecha de nacimiento, nacionalidad y documentos: bajan mucho los falsos positivos. */
function IdentityForm({ target, canEdit, onSaved }: { target: Target; canEdit: boolean; onSaved: (t: Target) => void }) {
  const person = target.kind === "Person";
  const [birth, setBirth] = useState(target.birthDate ?? "");
  const [nationality, setNationality] = useState(target.nationality ?? "");
  const [ids, setIds] = useState<Record<string, string>>({ rfc: "", curp: "", pasaporte: "", ...target.identifiers });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const { t } = useI18n();
  const keys = person ? ["rfc", "curp", "pasaporte"] : ["rfc"];

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    try {
      const saved = await api.updateTarget({
        ...target, birthDate: person && birth.trim() ? birth.trim() : null, nationality: nationality.trim() || null,
        identifiers: Object.fromEntries(Object.entries(ids).filter(([, v]) => v.trim())),
      });
      onSaved(saved);
      setMessage({ ok: true, text: t("Guardado. Se vuelve a revisar en menos de un minuto.") });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <form className="identity" onSubmit={save}>
      <p className="muted" style={{ margin: 0, fontSize: 12 }}>
        {t("Datos para distinguir homónimos. Un RFC o CURP igual confirma casi seguro; una fecha de nacimiento distinta descarta.")}
      </p>
      <div className="fields">
        {person && (
          <label>{t("Fecha de nacimiento")}
            <input disabled={!canEdit} placeholder={t("AAAA-MM-DD o AAAA")} pattern="\d{4}(-\d{2}-\d{2})?" value={birth}
              onChange={(e) => setBirth(e.target.value)} />
          </label>
        )}
        <label>{person ? t("Nacionalidad") : t("País")}
          <input disabled={!canEdit} placeholder={t("México")} value={nationality} onChange={(e) => setNationality(e.target.value)} />
        </label>
        {keys.map((k) => (
          <label key={k}>{k.toUpperCase()}
            <input disabled={!canEdit} value={ids[k] ?? ""} onChange={(e) => setIds({ ...ids, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {canEdit && <button type="submit">{t("Guardar datos")}</button>}
      {message && <span className={message.ok ? "ok" : "error"} role="status"> {message.text}</span>}
    </form>
  );
}
