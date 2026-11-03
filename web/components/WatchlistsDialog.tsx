"use client";

import { useEffect, useRef, useState } from "react";
import {
  api, uploadChangesCsvUrl, WATCHLIST_CATEGORIES, type ScreeningMatch, type UploadMode, type UploadResult, type Watchlist,
  type WatchlistUpload,
} from "@/lib/api";
import { Modal } from "./AccountDialogs";
import { MatchItem } from "./Screening";

const ago = (iso: string | null) => {
  if (!iso) return "nunca";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} min`;
  if (min < 48 * 60) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} días`;
};
const fmt = new Intl.NumberFormat("es-MX");
const when = (iso: string) =>
  new Date(iso).toLocaleString("es-MX", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function state(w: Watchlist): { label: string; className: string } {
  if (!w.enabled) return { label: "Apagada", className: "muted" };
  if (!w.configured) return { label: "Sin llave", className: "muted" };
  if (w.lastError) return { label: "Con error", className: "error" };
  if (!w.entryCount) return { label: "Esperando descarga", className: "muted" };
  return { label: "Al día", className: "ok" };
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

  const load = () => {
    api.watchlists().then(setLists).catch((err) => setError((err as Error).message));
    api.matches("pending").then((m) => { setPending(m); onChanged?.(m.length); }).catch((err) => setError((err as Error).message));
  };
  useEffect(load, []);

  return (
    <Modal title="Listas negras" onClose={onClose} wide>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "pending"} className={tab === "pending" ? "" : "ghost"} onClick={() => setTab("pending")}>
          Pendientes de revisar{pending ? ` (${pending.length})` : ""}
        </button>
        <button type="button" role="tab" aria-selected={tab === "lists"} className={tab === "lists" ? "" : "ghost"} onClick={() => setTab("lists")}>
          Listas
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {tab === "pending" ? (
        !pending ? <div className="empty">Cargando…</div> : pending.length === 0 ? (
          <p className="muted">No hay coincidencias pendientes en ningún objetivo.</p>
        ) : pending.map((m) => <MatchItem key={m.id} match={m} canReview={canReview} onChanged={load} showTarget />)
      ) : !lists ? <div className="empty">Cargando…</div> : (
        <>
          <div className="scroll-x"><table className="sources">
            <thead><tr><th>Lista</th><th>Tipo</th><th>Estado</th><th className="num">Registros</th><th>Revisada</th><th>Cambió</th><th /></tr></thead>
            <tbody>
              {lists.map((w) => {
                const st = state(w);
                return (
                  <tr key={w.slug}>
                    <td>
                      {w.infoUrl ? <a href={w.infoUrl} target="_blank" rel="noreferrer">{w.name}</a> : w.name}
                      <div className="muted" style={{ fontSize: 11 }}>{w.custom ? `Lista propia · ${w.uploadedBy ?? ""}` : w.license}</div>
                      {w.lastError && <code>{w.lastError}</code>}
                    </td>
                    <td>{w.categoryLabel}</td>
                    <td className={st.className}>{st.label}</td>
                    <td className="num">{fmt.format(w.entryCount)}</td>
                    <td className="muted">{ago(w.lastCheckedAt)}</td>
                    <td className="muted">{ago(w.lastChangedAt)}</td>
                    <td className="actions">{w.custom && (<>
                      <button type="button" className="ghost" onClick={() => setHistorySlug(w.slug)}>Historial</button>
                      {isAdmin && (
                        <button type="button" className="ghost" onClick={async () => {
                          if (!confirm(`¿Borrar la lista «${w.name}»? Sus coincidencias dejan de contar en el riesgo.`)) return;
                          await api.deleteWatchlist(w.slug).catch((err) => setError((err as Error).message));
                          load();
                        }}>Borrar</button>
                      )}
                    </>)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
          <p className="muted" style={{ fontSize: 12 }}>
            Las listas oficiales se descargan solas (OFAC cada 6 h, las demás cada día) y cada objetivo se vuelve a revisar
            cuando una cambia. La lista de la UIF solo puede cargarla un sujeto obligado.
          </p>
          {history && <UploadHistory key={`${history.slug}-${history.lastChangedAt}`} list={history} onClose={() => setHistorySlug(null)} />}
          {isAdmin && <UploadForm lists={lists} onUploaded={load} />}
        </>
      )}
    </Modal>
  );
}

const MODE_LABEL: Record<UploadMode, string> = { full: "Lista completa", update: "Actualización" };

function summary(r: UploadResult | WatchlistUpload): string {
  const other = r.changed - r.statusChanged;
  const parts = [
    `${fmt.format(r.added)} altas`,
    `${fmt.format(r.statusChanged)} cambios de estatus`,
    `${fmt.format(other)} otros cambios`,
    `${fmt.format(r.unchanged)} sin cambio`,
  ];
  if (r.mode === "full") parts.push(`${fmt.format(r.removed)} retirados`);
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
  const listName = mode === "update" ? target : name.trim();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !listName) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (!file.size) throw new Error(`El archivo «${file.name}» está vacío.`);
      setResult(await api.uploadWatchlist(listName, category, file, mode));
      onUploaded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack upload" onSubmit={submit}>
      <h3>Cargar lista propia</h3>
      <div className="tabs" role="radiogroup" aria-label="Tipo de carga">
        {(["full", "update"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? "" : "ghost"}
            disabled={m === "update" && !custom.length} onClick={() => { setMode(m); setResult(null); }}>
            {MODE_LABEL[m]}
          </button>
        ))}
      </div>
      {mode === "full" ? (
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          El archivo trae la lista entera. Si ya existe una lista con el mismo nombre, se reemplaza: quien no venga en el
          archivo sale de la lista. CSV o JSON con una columna de nombre (name o nombre); también se usan alias,
          birth_date, nationality, rfc, curp, id_num, list, position, department, program, publication_date, status y
          location. También acepta el archivo PEP separado por &quot;|&quot; sin encabezado, nacional
          (nombre|cargo|dependencia|rfc|fecha de nacimiento|país|estatus 1 o 0) o internacional (nombre|fecha de
          nacimiento|cargo|país|estatus||dependencia).
        </p>
      ) : (
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          El archivo trae solo altas y cambios, en el mismo formato que la lista completa. Se agregan las personas nuevas
          y se actualizan las que cambiaron (quien deja el cargo llega con estatus 0 y pasa a «Inactivo»); nadie sale de
          la lista. Cada persona se reconoce por su RFC o, si no lo tiene, por nombre, fecha de nacimiento y cargo. Cada
          cambio queda en el historial con la fecha, y las coincidencias confirmadas toman el estatus nuevo.
        </p>
      )}
      {mode === "update" ? (
        <label>Lista que se actualiza
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {custom.map((w) => <option key={w.slug} value={w.name}>{w.name} ({fmt.format(w.entryCount)})</option>)}
          </select>
        </label>
      ) : (
        <>
          <label>Nombre de la lista<input required value={name} onChange={(e) => setName(e.target.value)} placeholder="PEP México" /></label>
          <label>Tipo
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {Object.entries(WATCHLIST_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </>
      )}
      <label>Archivo<input type="file" required accept=".csv,.json,.txt,.psv,.dat,text/csv,text/plain,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      {error && <p className="error" role="status">{error}</p>}
      {result && (
        <div className="ok upload-result" role="status">
          <b>{result.mode === "update" ? "Actualización aplicada" : "Lista cargada"}:</b> {fmt.format(result.rows)} filas leídas.
          <div>{summary(result)}</div>
          <div>La lista queda con {fmt.format(result.entries)} registros.
            {result.uploadId != null && hasDetail(result) && (
              <> <a href={uploadChangesCsvUrl(result.uploadId)} download>Descargar el detalle (CSV)</a></>
            )}
          </div>
        </div>
      )}
      <button type="submit" disabled={busy || !listName}>
        {busy ? "Cargando… (una lista grande tarda unos minutos)" : mode === "update" ? "Aplicar actualización" : "Cargar"}
      </button>
    </form>
  );
}

/** Cargas de una lista propia: completas y de actualización, con sus conteos y el detalle descargable. */
function UploadHistory({ list, onClose }: { list: Watchlist; onClose: () => void }) {
  const [uploads, setUploads] = useState<WatchlistUpload[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, []);
  useEffect(() => {
    setUploads(null);
    api.watchlistUploads(list.slug).then(setUploads).catch((err) => setError((err as Error).message));
  }, [list.slug]);

  return (
    <section className="upload-history" ref={ref}>
      <header>
        <h3>Historial de cargas · {list.name}</h3>
        <button type="button" className="ghost" onClick={onClose}>Cerrar</button>
      </header>
      {error && <p className="error">{error}</p>}
      {!uploads ? <div className="empty">Cargando…</div> : uploads.length === 0 ? (
        <p className="muted">Esta lista se cargó antes de que se guardara el historial.</p>
      ) : (
        <div className="scroll-x"><table className="sources">
          <thead><tr>
            <th>Fecha</th><th>Tipo</th><th className="num">Altas</th><th className="num">Estatus</th>
            <th className="num">Otros</th><th className="num">Sin cambio</th><th className="num">Retirados</th><th className="num">Total</th><th />
          </tr></thead>
          <tbody>
            {uploads.map((u) => (
              <tr key={u.id}>
                <td>
                  {when(u.at)}
                  <div className="muted" style={{ fontSize: 11 }}>{[u.fileName, u.uploadedBy].filter(Boolean).join(" · ")}</div>
                </td>
                <td>{MODE_LABEL[u.mode]}</td>
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
        En la primera carga de una lista no se anotan las altas una por una. Estatus = personas que pasaron de activas a
        inactivas o al revés.
      </p>
    </section>
  );
}
