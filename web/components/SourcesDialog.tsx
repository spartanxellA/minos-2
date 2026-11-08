"use client";

import { useEffect, useState } from "react";
import { api, SOURCE_LABEL, type SourcesStatus, type SourceStatus } from "@/lib/api";
import { Modal } from "./AccountDialogs";
import { msg, translate as t, useI18n } from "@/lib/i18n";

const CHANNEL_LABEL: Record<string, string> = { email: msg("Correo"), webhook: msg("Webhook (Slack, Teams…)"), whatsapp: "WhatsApp" };
const ago = (iso: string | null) => {
  if (!iso) return t("nunca");
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return t("hace un momento");
  if (min < 60) return t("hace {n} min", { n: min });
  if (min < 48 * 60) return t("hace {n} h", { n: Math.round(min / 60) });
  return t("hace {n} días", { n: Math.round(min / 1440) });
};

function state(s: SourceStatus): { label: string; className: string } {
  if (!s.configured) return { label: msg("Sin llave"), className: "muted" };
  if (s.errors.length) return { label: msg("Con errores"), className: "error" };
  if (s.warnings.length) return { label: msg("Con avisos"), className: "warn" };
  if (!s.lastRunAt && !s.lastMentionAt) return { label: msg("Esperando"), className: "muted" };
  return { label: msg("Activa"), className: "ok" };
}

/** Estado de cada fuente y canal de avisos, para no tener que revisar los registros del servidor. */
export function SourcesDialog({ onClose, onLoaded, isAdmin }: {
  onClose: () => void; onLoaded?: (errors: number) => void; isAdmin: boolean;
}) {
  const [data, setData] = useState<SourcesStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const { tApi, locale } = useI18n();
  const source = (s: string) => (SOURCE_LABEL[s] ? t(SOURCE_LABEL[s]) : s);

  // El botón «Actualizar» vuelve a leer el estado; sin indicador parecía que no hacía nada,
  // porque casi siempre el estado no cambia entre un clic y otro.
  const load = () => {
    setLoading(true);
    return api.sources().then((d) => {
      setData(d);
      setError(null);
      setLoadedAt(new Date());
      onLoaded?.(d.sources.filter((s) => s.errors.length).length);
    }).catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  return (
    <Modal title={t("Fuentes y avisos")} onClose={onClose} wide>
      {error && <p className="error">{error}</p>}
      {!data ? <div className="empty">{t("Cargando…")}</div> : (
        <>
          <table className="sources">
            <thead><tr><th>{t("Fuente")}</th><th>{t("Estado")}</th><th>{t("Última consulta")}</th><th>{t("Última nota")}</th><th>{t("Notas 24 h")}</th></tr></thead>
            <tbody>
              {data.sources.map((s) => {
                const st = state(s);
                return (
                  <tr key={s.source}>
                    <td>{source(s.source)}</td>
                    <td className={st.className}>{t(st.label)}</td>
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
              <h3>{t("Errores")}</h3>
              {data.sources.filter((s) => s.errors.length).map((s) => s.errors.map((e) => (
                <div key={`${s.source}-${e.targetId}`} className="source-error">
                  <strong>{source(s.source)}</strong> · {e.targetName} <span className="muted">· {ago(e.at)}</span>
                  <code>{tApi(e.error)}</code>
                </div>
              )))}
              {isAdmin && <p className="muted" style={{ fontSize: 12 }}>
                {t("Un 401 o 403 casi siempre es una llave mal copiada o un plan que no incluye esa función. El error se borra solo cuando la siguiente consulta funciona.")}
              </p>}
            </>
          )}

          {data.sources.some((s) => s.warnings.length) && (
            <>
              <h3>{t("Avisos")}</h3>
              {data.sources.filter((s) => s.warnings.length).map((s) => s.warnings.map((w) => (
                <div key={`${s.source}-${w.text}`} className="source-error warn">
                  <strong>{source(s.source)}</strong>{" "}
                  <span className="muted" title={w.targets.join(", ")}>
                    · {w.targets.length === 1 ? t("afecta a 1 objetivo") : t("afecta a {n} objetivos", { n: w.targets.length })} · {ago(w.at)}
                  </span>
                  <code>{tApi(w.text)}</code>
                </div>
              )))}
              <p className="muted" style={{ fontSize: 12 }}>
                {t("La fuente sigue funcionando; solo esos feeds se saltan mientras dura la pausa.")}
              </p>
            </>
          )}

          <h3>{t("Avisos de alertas")}</h3>
          <div className="row">
            {data.channels.map((c) => (
              <span key={c.channel} className={`pill-outline ${c.configured ? "ok" : "muted"}`}>
                {CHANNEL_LABEL[c.channel] ? t(CHANNEL_LABEL[c.channel]) : c.channel}: {c.configured ? t("activo") : t("sin configurar")}
              </span>
            ))}
          </div>
          {isAdmin && (
            <p className="muted" style={{ fontSize: 12 }}>
              {t("Las llaves se ponen en el archivo .env del servidor; después hay que correr")} <code>minos up -d</code>.
            </p>
          )}
          <div className="row" style={{ alignItems: "center", gap: 12 }}>
            <button type="button" className="ghost" onClick={load} disabled={loading}>
              {loading ? t("Actualizando…") : t("Actualizar")}
            </button>
            {loadedAt && !loading && (
              <span className="muted" style={{ fontSize: 12 }} aria-live="polite">
                {t("Actualizado a las {time}", { time: loadedAt.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) })}
              </span>
            )}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            {t("«Actualizar» vuelve a leer el estado. Cada fuente se consulta sola cada pocos minutos y las pausas terminan solas; si nada cambió, el estado se ve igual.")}
          </p>
        </>
      )}
    </Modal>
  );
}
