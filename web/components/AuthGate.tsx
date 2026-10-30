"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, UNAUTHORIZED_EVENT, type Me } from "@/lib/api";
import { useIdleLogout } from "@/lib/useIdleLogout";
import { Dashboard } from "./Dashboard";
import { Logo } from "./Logo";

/** Muestra el inicio de sesión hasta que haya una sesión válida; si la sesión vence, vuelve a él. */
export function AuthGate() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [offline, setOffline] = useState(false);
  // Por qué se volvió a la pantalla de entrada, para decírselo a la persona.
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch((err) => {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else setOffline(true);
    });
    const expired = () => setMe((prev) => {
      if (prev) setNotice("Tu sesión se cerró. Vuelve a entrar.");
      return null;
    });
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired);
  }, []);

  if (offline) return <div className="login"><div className="card">No se pudo conectar con la API. Revisa que esté corriendo.</div></div>;
  if (me === undefined) return null;
  if (me === null) return <LoginForm notice={notice} onLogin={(m) => { setNotice(null); setMe(m); }} />;
  return (
    <>
      <Dashboard user={me} onLogout={async () => { await api.logout().catch(() => {}); setMe(null); }} />
      <IdleGuard user={me} onIdle={async () => {
        const minutes = Math.max(1, Math.round((me.idleTimeoutSeconds ?? 0) / 60));
        setMe(null);
        setNotice(`Cerramos tu sesión porque pasaron ${minutes} ${minutes === 1 ? "minuto" : "minutos"} sin actividad.`);
        await api.logout("idle").catch(() => {});
      }} />
    </>
  );
}

/** Cuenta el tiempo sin actividad, avisa antes de cerrar la sesión y la cierra al vencer. */
function IdleGuard({ user, onIdle }: { user: Me; onIdle: () => void }) {
  const { warningLeft, stay } = useIdleLogout(user.authMode === "local" ? user.idleTimeoutSeconds : null, onIdle);
  const ref = useRef<HTMLDialogElement>(null);

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
      <header><h2 id="idle-title">¿Sigues ahí?</h2></header>
      <div className="body stack">
        <p>Por seguridad, tu sesión se cerrará en <strong className="countdown">{clock}</strong> si no hay actividad.</p>
        <div className="row">
          <button type="button" onClick={stay} autoFocus>Seguir conectado</button>
          <button type="button" className="ghost" onClick={onIdle}>Cerrar sesión</button>
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
        <p className="muted">Monitoreo de riesgo reputacional</p>
        {notice && <p className="notice" role="status">{notice}</p>}
        <label>
          Correo
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </label>
        <label>
          Contraseña
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </div>
  );
}
