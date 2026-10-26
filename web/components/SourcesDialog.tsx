"use client";

import { useEffect, useState } from "react";
import { api, SOURCE_LABEL, type SourcesStatus, type SourceStatus } from "@/lib/api";
import { Modal } from "./AccountDialogs";

const CHANNEL_LABEL: Record<string, string> = { email: "Correo", webhook: "Webhook (Slack, Teams…)", whatsapp: "WhatsApp" };
const ago = (iso: string | null) => {
  if (!iso) return "nunca";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} min`;
  if (min < 48 * 60) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} días`;
};

function state(s: SourceStatus): { label: string; className: string } {
  if (!s.configured) return { label: "Sin llave", className: "muted" };
  if (s.errors.length) return { label: "Con errores", className: "error" };
  if (!s.lastRunAt && !s.lastMentionAt) return { label: "Esperando", className: "muted" };
  return { label: "Activa", className: "ok" };
}

/** Estado de cada fuente y canal de avisos, para no tener que revisar los registros del servidor. */
export function SourcesDialog({ onClose, onLoaded }: { onClose: () => void; onLoaded?: (errors: number) => void }) {
  const [data, setData] = useState<SourcesStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.sources().then((d) => {
    setData(d);
    onLoaded?.(d.sources.filter((s) => s.errors.length).length);
  }).catch((err) => setError((err as Error).message));
  useEffect(() => { load(); }, []);

  return (
    <Modal title="Fuentes y avisos" onClose={onClose} wide>
      {error && <p className="error">{error}</p>}
      {!data ? <div className="empty">Cargando…</div> : (
        <>
          <table className="sources">
            <thead><tr><th>Fuente</th><th>Estado</th><th>Última consulta</th><th>Última nota</th><th>Notas 24 h</th></tr></thead>
            <tbody>
              {data.sources.map((s) => {
                const st = state(s);
                return (
                  <tr key={s.source}>
                    <td>{SOURCE_LABEL[s.source] ?? s.source}</td>
                    <td className={st.className}>{st.label}</td>
                    <td className="muted">{s.configured ? ago(s.lastRunAt) : "—"}</td>
                    <td className="muted">{s.configured ? ago(s.lastMentionAt) : "—"}</td>
                    <td>{s.configured ? s.mentionsLastDay : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {data.sources.some((s) => s.errors.length) && (
            <>
              <h3>Errores</h3>
              {data.sources.filter((s) => s.errors.length).map((s) => s.errors.map((e) => (
                <div key={`${s.source}-${e.targetId}`} className="source-error">
                  <strong>{SOURCE_LABEL[s.source] ?? s.source}</strong> · {e.targetName} <span className="muted">· {ago(e.at)}</span>
                  <code>{e.error}</code>
                </div>
              )))}
              <p className="muted" style={{ fontSize: 12 }}>
                Un 401 o 403 casi siempre es una llave mal copiada o un plan que no incluye esa función. El error se borra
                solo cuando la siguiente consulta funciona.
              </p>
            </>
          )}

          <h3>Avisos de alertas</h3>
          <div className="row">
            {data.channels.map((c) => (
              <span key={c.channel} className={`pill-outline ${c.configured ? "ok" : "muted"}`}>
                {CHANNEL_LABEL[c.channel] ?? c.channel}: {c.configured ? "activo" : "sin configurar"}
              </span>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Las llaves se ponen en el archivo .env del servidor; después hay que correr <code>minos up -d</code>.
          </p>
          <button type="button" className="ghost" onClick={load}>Actualizar</button>
        </>
      )}
    </Modal>
  );
}
