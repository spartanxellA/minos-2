"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, UNAUTHORIZED_EVENT, type Me } from "@/lib/api";
import { useIdleLogout } from "@/lib/useIdleLogout";
import { Dashboard } from "./Dashboard";
import { Logo } from "./Logo";
import { isLang, LanguageSelect, msg, translate, useI18n } from "@/lib/i18n";

/** Muestra el inicio de sesión hasta que haya una sesión válida; si la sesión vence, vuelve a él. */
export function AuthGate() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [offline, setOffline] = useState(false);
  // Por qué se volvió a la pantalla de entrada, para decírselo a la persona.
  const [notice, setNotice] = useState<string | null>(null);
  const { t, setLang } = useI18n();
  // El idioma guardado en la cuenta manda sobre el del navegador.
  const signedIn = (m: Me) => {
    if (isLang(m.language)) setLang(m.language);
    setMe(m);
  };

  useEffect(() => {
    api.me().then(signedIn).catch((err) => {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else setOffline(true);
    });
    const expired = () => setMe((prev) => {
      if (prev) setNotice(msg("Tu sesión se cerró. Vuelve a entrar."));
      return null;
    });
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired);
  }, []);

  if (offline) return <div className="login"><div className="card">{t("No se pudo conectar con la API. Revisa que esté corriendo.")}</div></div>;
  if (me === undefined) return null;
  if (me === null) return <LoginForm notice={notice} onLogin={(m) => { setNotice(null); signedIn(m); }} />;
  return (
    <>
      <Dashboard user={me} onLogout={async () => { await api.logout().catch(() => {}); setMe(null); }} />
      <IdleGuard user={me} onIdle={async () => {
        const minutes = Math.max(1, Math.round((me.idleTimeoutSeconds ?? 0) / 60));
        setMe(null);
        // Se guarda en español y se traduce al mostrarlo, por si la persona cambia el idioma en la pantalla de entrada.
        setNotice(minutes === 1 ? msg("Cerramos tu sesión porque pasó 1 minuto sin actividad.")
          : translate("Cerramos tu sesión porque pasaron {n} minutos sin actividad.", { n: String(minutes) }, "es"));
        await api.logout("idle").catch(() => {});
      }} />
    </>
  );
}

/** Cuenta el tiempo sin actividad, avisa antes de cerrar la sesión y la cierra al vencer. */
function IdleGuard({ user, onIdle }: { user: Me; onIdle: () => void }) {
  const { warningLeft, stay } = useIdleLogout(user.authMode === "local" ? user.idleTimeoutSeconds : null, onIdle);
  const ref = useRef<HTMLDialogElement>(null);
  const { t } = useI18n();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (warningLeft !== null && !d.open) d.showModal();
    if (warningLeft === null && d.open) d.close();
  }, [warningLeft]);

  const left = warningLeft ?? 0;
  const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    // Cerrar el aviso con Esc también cuenta como seguir conectado.
    <dialog ref={ref} className="modal idle-warning" role="alertdialog" aria-labelledby="idle-title"
      onCancel={(e) => { e.preventDefault(); stay(); }}>
      <header><h2 id="idle-title">{t("¿Sigues ahí?")}</h2></header>
      <div className="body stack">
        <p>{t("Por seguridad, tu sesión se cerrará en")} <strong className="countdown">{clock}</strong> {t("si no hay actividad.")}</p>
        <div className="row">
          <button type="button" onClick={stay} autoFocus>{t("Seguir conectado")}</button>
          <button type="button" className="ghost" onClick={onIdle}>{t("Cerrar sesión")}</button>
        </div>
      </div>
    </dialog>
  );
}

function LoginForm({ notice, onLogin }: { notice: string | null; onLogin: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { t, tApi } = useI18n();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api.login(email, password));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <Logo size={64} />
        <h1>min<span>OS</span> 2.0</h1>
        <p className="muted">{t("Monitoreo de riesgo reputacional")}</p>
        {notice && <p className="notice" role="status">{tApi(notice)}</p>}
        <label>
          {t("Correo")}
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </label>
        <label>
          {t("Contraseña")}
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? t("Entrando…") : t("Entrar")}</button>
        <LanguageSelect className="lang login-lang" />
      </form>
    </div>
  );
}
