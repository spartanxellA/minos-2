"use client";

import { useEffect, useState } from "react";
import { api, WATCHLIST_CATEGORIES, type ScreeningMatch, type Watchlist } from "@/lib/api";
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
            <thead><tr><th>Lista</th><th>Tipo</th><th>Estado</th><th className="num">Registros</th><th>Revisada</th><th>Cambió</th>{isAdmin && <th />}</tr></thead>
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
                    {isAdmin && (
                      <td>{w.custom && (
                        <button type="button" className="ghost" onClick={async () => {
                          if (!confirm(`¿Borrar la lista «${w.name}»? Sus coincidencias dejan de contar en el riesgo.`)) return;
                          await api.deleteWatchlist(w.slug).catch((err) => setError((err as Error).message));
                          load();
                        }}>Borrar</button>
                      )}</td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table></div>
          <p className="muted" style={{ fontSize: 12 }}>
            Las listas oficiales se descargan solas (OFAC cada 6 h, las demás cada día) y cada objetivo se vuelve a revisar
            cuando una cambia. La lista de la UIF solo puede cargarla un sujeto obligado.
          </p>
          {isAdmin && <UploadForm onUploaded={load} />}
        </>
      )}
    </Modal>
  );
}

/** Los archivos que salen de Excel o de sistemas viejos suelen venir en Windows-1252, no en UTF-8. */
async function readText(file: File) {
  const bytes = await file.arrayBuffer();
  const head = new Uint8Array(bytes.slice(0, 2));
  // "Texto Unicode" de Excel: UTF-16 con marca al inicio.
  if ((head[0] === 0xff && head[1] === 0xfe) || (head[0] === 0xfe && head[1] === 0xff)) {
    return new TextDecoder(head[0] === 0xff ? "utf-16le" : "utf-16be").decode(bytes);
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder("windows-1252").decode(bytes);
  }
}

function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("pep");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !name.trim()) return;
    setBusy(true);
    try {
      const text = await readText(file);
      if (!text.trim()) throw new Error(`El archivo «${file.name}» está vacío.`);
      const r = await api.uploadWatchlist(name.trim(), category, text);
      setMessage({ ok: true, text: `${fmt.format(r.entries)} registros (${r.added} nuevos, ${r.changed} cambiados, ${r.removed} retirados).` });
      onUploaded();
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack upload" onSubmit={submit}>
      <h3>Cargar lista propia</h3>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        CSV o JSON con una columna de nombre (name o nombre). También se usan: alias, birth_date, nationality, rfc, curp,
        id_num, list, position, department, program, publication_date, status y location. También acepta el archivo PEP
        separado por &quot;|&quot; sin encabezado (nombre|cargo|dependencia|rfc|fecha de nacimiento|país|estatus 1 o 0). Si ya existe una lista con el
        mismo nombre, se reemplaza.
      </p>
      <label>Nombre de la lista<input required value={name} onChange={(e) => setName(e.target.value)} placeholder="PEP México" /></label>
      <label>Tipo
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {Object.entries(WATCHLIST_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label>Archivo<input type="file" required accept=".csv,.json,.txt,.psv,.dat,text/csv,text/plain,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      {message && <p className={message.ok ? "ok" : "error"} role="status">{message.text}</p>}
      <button type="submit" disabled={busy}>{busy ? "Cargando…" : "Cargar"}</button>
    </form>
  );
}
