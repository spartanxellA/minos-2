"use client";

import { useEffect, useRef, useState } from "react";
import {
  api, uploadChangesCsvUrl, WATCHLIST_CATEGORIES, type ScreeningMatch, type UploadMode, type UploadResult, type Watchlist,
  type WatchlistUpload,
} from "@/lib/api";
import { Modal } from "./AccountDialogs";
import { MatchItem } from "./Screening";
import { locale, msg, translate as t, useI18n } from "@/lib/i18n";

const ago = (iso: string | null) => {
  if (!iso) return t("nunca");
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return t("hace un momento");
  if (min < 60) return t("hace {n} min", { n: min });
  if (min < 48 * 60) return t("hace {n} h", { n: Math.round(min / 60) });
  return t("hace {n} días", { n: Math.round(min / 1440) });
};
// Se piden al pintar: así toman el formato del idioma activo.
const fmt = { format: (n: number) => new Intl.NumberFormat(locale()).format(n) };
const when = (iso: string) =>
  new Date(iso).toLocaleString(locale(), { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function state(w: Watchlist): { label: string; className: string } {
  if (!w.enabled) return { label: msg("Apagada"), className: "muted" };
  if (!w.configured) return { label: msg("Sin llave"), className: "muted" };
  if (w.lastError) return { label: msg("Con error"), className: "error" };
  if (!w.entryCount) return { label: msg("Esperando descarga"), className: "muted" };
  return { label: msg("Al día"), className: "ok" };
}

/** Pendientes de revisar de todos los objetivos, y el estado de cada lista (oficiales y propias). */
export function WatchlistsDialog({ canReview, isAdmin, onClose, onChanged }: {
  canReview: boolean;
  isAdmin: boolean;
  onClose: () => void;
  onChanged?: (pending: number) => void;
}) {
  const [tab, setTab] = useState<"pending" | "lists">("pending");
  const [lists, setLists] = useState<Watchlist[] | null>(null);
  const [pending, setPending] = useState<ScreeningMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historySlug, setHistorySlug] = useState<string | null>(null);
  const history = lists?.find((w) => w.slug === historySlug) ?? null;
  const { tApi } = useI18n();

  const load = () => {
    api.watchlists().then(setLists).catch((err) => setError((err as Error).message));
    api.matches("pending").then((m) => { setPending(m); onChanged?.(m.length); }).catch((err) => setError((err as Error).message));
  };
  useEffect(load, []);

  return (
    <Modal title={t("Listas negras")} onClose={onClose} wide>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "pending"} className={tab === "pending" ? "" : "ghost"} onClick={() => setTab("pending")}>
          {t("Pendientes de revisar")}{pending ? ` (${pending.length})` : ""}
        </button>
        <button type="button" role="tab" aria-selected={tab === "lists"} className={tab === "lists" ? "" : "ghost"} onClick={() => setTab("lists")}>
          {t("Listas")}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {tab === "pending" ? (
        !pending ? <div className="empty">{t("Cargando…")}</div> : pending.length === 0 ? (
          <p className="muted">{t("No hay coincidencias pendientes en ningún objetivo.")}</p>
        ) : pending.map((m) => <MatchItem key={m.id} match={m} canReview={canReview} onChanged={load} showTarget />)
      ) : !lists ? <div className="empty">{t("Cargando…")}</div> : (
        <>
          <div className="scroll-x"><table className="sources">
            <thead><tr><th>{t("Lista")}</th><th>{t("Tipo")}</th><th>{t("Estado")}</th><th className="num">{t("Registros")}</th><th>{t("Revisada")}</th><th>{t("Cambió")}</th><th /></tr></thead>
            <tbody>
              {lists.map((w) => {
                const st = state(w);
                return (
                  <tr key={w.slug}>
                    <td>
                      {w.infoUrl ? <a href={w.infoUrl} target="_blank" rel="noreferrer">{w.name}</a> : w.name}
                      <div className="muted" style={{ fontSize: 11 }}>{w.custom ? `${t("Lista propia")} · ${w.uploadedBy ?? ""}` : tApi(w.license)}</div>
                      {w.lastError && <code>{tApi(w.lastError)}</code>}
                    </td>
                    <td>{tApi(w.categoryLabel)}</td>
                    <td className={st.className}>{t(st.label)}</td>
                    <td className="num">{fmt.format(w.entryCount)}</td>
                    <td className="muted">{ago(w.lastCheckedAt)}</td>
                    <td className="muted">{ago(w.lastChangedAt)}</td>
                    <td className="actions">{w.custom && (<>
                      <button type="button" className="ghost" onClick={() => setHistorySlug(w.slug)}>{t("Historial")}</button>
                      {isAdmin && (
                        <button type="button" className="ghost" onClick={async () => {
                          if (!confirm(t("¿Borrar la lista «{name}»? Sus coincidencias dejan de contar en el riesgo.", { name: w.name }))) return;
                          await api.deleteWatchlist(w.slug).catch((err) => setError((err as Error).message));
                          load();
                        }}>{t("Borrar")}</button>
                      )}
                    </>)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
          <p className="muted" style={{ fontSize: 12 }}>
            {t("Las listas oficiales se descargan solas (OFAC cada 6 h, las demás cada día) y cada objetivo se vuelve a revisar cuando una cambia. La lista de la UIF solo puede cargarla un sujeto obligado.")}
          </p>
          {history && <UploadHistory key={`${history.slug}-${history.lastChangedAt}`} list={history} onClose={() => setHistorySlug(null)} />}
          {isAdmin && <UploadForm lists={lists} onUploaded={load} />}
        </>
      )}
    </Modal>
  );
}

const MODE_LABEL: Record<UploadMode, string> = { full: msg("Lista completa"), update: msg("Actualización") };

function summary(r: UploadResult | WatchlistUpload): string {
  const other = r.changed - r.statusChanged;
  const parts = [
    t("{n} altas", { n: r.added }),
    t("{n} cambios de estatus", { n: r.statusChanged }),
    t("{n} otros cambios", { n: other }),
    t("{n} sin cambio", { n: r.unchanged }),
  ];
  if (r.mode === "full") parts.push(t("{n} retirados", { n: r.removed }));
  return parts.join(" · ");
}

/** La primera carga de una lista no anota las altas una por una: su detalle saldría vacío. */
const hasDetail = (u: UploadResult | WatchlistUpload) =>
  u.changed + u.removed > 0 || (u.added > 0 && !(u.mode === "full" && u.added === u.entries));

function UploadForm({ lists, onUploaded }: { lists: Watchlist[]; onUploaded: () => void }) {
  const custom = lists.filter((w) => w.custom);
  const [mode, setMode] = useState<UploadMode>("full");
  const [name, setName] = useState("");
  const [target, setTarget] = useState(custom[0]?.name ?? "");
  const [category, setCategory] = useState("pep");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useI18n(); // vuelve a pintar al cambiar de idioma
  const NEW = "__nueva__";
  const [replace, setReplace] = useState(custom[0]?.name ?? NEW);
  const replacing = mode === "full" && replace !== NEW ? custom.find((w) => w.name === replace) : undefined;
  const listName = mode === "update" ? target : replacing ? replacing.name : name.trim();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !listName) return;
    if (replacing && !confirm(t("Se reemplaza «{name}» ({n} registros): quien no venga en el archivo sale de la lista.", { name: replacing.name, n: replacing.entryCount }) + "\n\n" + t("Si el archivo trae solo altas y cambios, cancela y elige «Actualización»."))) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (!file.size) throw new Error(t("El archivo «{name}» está vacío.", { name: file.name }));
      setResult(await api.uploadWatchlist(listName, replacing ? replacing.category : category, file, mode));
      onUploaded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack upload" onSubmit={submit}>
      <h3>{t("Cargar lista propia")}</h3>
      <div className="tabs" role="radiogroup" aria-label={t("Tipo de carga")}>
        {(["full", "update"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? "" : "ghost"}
            disabled={m === "update" && !custom.length} onClick={() => { setMode(m); setResult(null); }}>
            {t(MODE_LABEL[m])}
          </button>
        ))}
      </div>
      {mode === "full" ? (
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          {t("El archivo trae la lista entera. Si ya existe una lista con el mismo nombre, se reemplaza: quien no venga en el archivo sale de la lista. CSV o JSON con una columna de nombre (name o nombre); también se usan alias, birth_date, nationality, rfc, curp, id_num, list, position, department, program, publication_date, status y location. También acepta el archivo PEP separado por \"|\" sin encabezado, nacional (nombre|cargo|dependencia|rfc|fecha de nacimiento|país|estatus 1 o 0) o internacional (nombre|fecha de nacimiento|cargo|país|estatus||dependencia).")}
        </p>
      ) : (
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          {t("El archivo trae solo altas y cambios, en el mismo formato que la lista completa. Se agregan las personas nuevas y se actualizan las que cambiaron (quien deja el cargo llega con estatus 0 y pasa a «Inactivo»); nadie sale de la lista. Cada persona se reconoce por su RFC o, si no lo tiene, por nombre, fecha de nacimiento y cargo. Cada cambio queda en el historial con la fecha, y las coincidencias confirmadas toman el estatus nuevo.")}
        </p>
      )}
      {mode === "update" ? (
        <label>{t("Lista que se actualiza")}
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {custom.map((w) => <option key={w.slug} value={w.name}>{w.name} ({fmt.format(w.entryCount)})</option>)}
          </select>
        </label>
      ) : (
        <>
          {custom.length > 0 && (
            <label>{t("Lista")}
              <select value={replace} onChange={(e) => setReplace(e.target.value)}>
                {custom.map((w) => <option key={w.slug} value={w.name}>{t("Reemplazar «{name}» ({n})", { name: w.name, n: w.entryCount })}</option>)}
                <option value={NEW}>{t("Nueva lista…")}</option>
              </select>
            </label>
          )}
          {!replacing && (
            <>
              <label>{t("Nombre de la lista")}<input required value={name} onChange={(e) => setName(e.target.value)} placeholder={t("PEP México")} /></label>
              <label>{t("Tipo")}
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  {Object.entries(WATCHLIST_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
                </select>
              </label>
            </>
          )}
        </>
      )}
      <label>{t("Archivo")}<input type="file" required accept=".csv,.json,.txt,.psv,.dat,text/csv,text/plain,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      {error && <p className="error" role="status">{error}</p>}
      {result && (
        <div className="ok upload-result" role="status">
          <b>{result.mode === "update" ? t("Actualización aplicada") : t("Lista cargada")}:</b> {t("{n} filas leídas.", { n: result.rows })}
          <div>{summary(result)}</div>
          <div>{t("La lista queda con {n} registros.", { n: result.entries })}
            {result.uploadId != null && hasDetail(result) && (
              <> <a href={uploadChangesCsvUrl(result.uploadId)} download>{t("Descargar el detalle (CSV)")}</a></>
            )}
          </div>
        </div>
      )}
      <button type="submit" disabled={busy}>
        {busy ? t("Cargando… (una lista grande tarda unos minutos)") : mode === "update" ? t("Aplicar actualización") : t("Cargar")}
      </button>
    </form>
  );
}

/** Cargas de una lista propia: completas y de actualización, con sus conteos y el detalle descargable. */
function UploadHistory({ list, onClose }: { list: Watchlist; onClose: () => void }) {
  const [uploads, setUploads] = useState<WatchlistUpload[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLElement>(null);
  useI18n();
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, []);
  useEffect(() => {
    setUploads(null);
    api.watchlistUploads(list.slug).then(setUploads).catch((err) => setError((err as Error).message));
  }, [list.slug]);

  return (
    <section className="upload-history" ref={ref}>
      <header>
        <h3>{t("Historial de cargas")} · {list.name}</h3>
        <button type="button" className="ghost" onClick={onClose}>{t("Cerrar")}</button>
      </header>
      {error && <p className="error">{error}</p>}
      {!uploads ? <div className="empty">{t("Cargando…")}</div> : uploads.length === 0 ? (
        <p className="muted">{t("Esta lista se cargó antes de que se guardara el historial.")}</p>
      ) : (
        <div className="scroll-x"><table className="sources">
          <thead><tr>
            <th>{t("Fecha")}</th><th>{t("Tipo")}</th><th className="num">{t("Altas")}</th><th className="num">{t("Estatus")}</th>
            <th className="num">{t("Otros")}</th><th className="num">{t("Sin cambio")}</th><th className="num">{t("Retirados")}</th><th className="num">{t("Total")}</th><th />
          </tr></thead>
          <tbody>
            {uploads.map((u) => (
              <tr key={u.id}>
                <td>
                  {when(u.at)}
                  <div className="muted" style={{ fontSize: 11 }}>{[u.fileName, u.uploadedBy].filter(Boolean).join(" · ")}</div>
                </td>
                <td>{t(MODE_LABEL[u.mode])}</td>
                <td className="num">{fmt.format(u.added)}</td>
                <td className="num">{fmt.format(u.statusChanged)}</td>
                <td className="num">{fmt.format(u.changed - u.statusChanged)}</td>
                <td className="num">{fmt.format(u.unchanged)}</td>
                <td className="num">{u.mode === "full" ? fmt.format(u.removed) : "—"}</td>
                <td className="num">{fmt.format(u.entries)}</td>
                <td>{hasDetail(u) && <a href={uploadChangesCsvUrl(u.id)} download>CSV</a>}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        {t("En la primera carga de una lista no se anotan las altas una por una. Estatus = personas que pasaron de activas a inactivas o al revés.")}
      </p>
    </section>
  );
}
