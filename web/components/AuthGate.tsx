"use client";

import { useEffect, useState } from "react";
import { api, ApiError, UNAUTHORIZED_EVENT, type Me } from "@/lib/api";
import { Dashboard } from "./Dashboard";
import { Logo } from "./Logo";

/** Muestra el inicio de sesión hasta que haya una sesión válida; si la sesión vence, vuelve a él. */
export function AuthGate() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.me().then(setMe).catch((err) => {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else setOffline(true);
    });
    const expired = () => setMe(null);
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired);
  }, []);

  if (offline) return <div className="login"><div className="card">No se pudo conectar con la API. Revisa que esté corriendo.</div></div>;
  if (me === undefined) return null;
  if (me === null) return <LoginForm onLogin={setMe} />;
  return <Dashboard user={me} onLogout={async () => { await api.logout().catch(() => {}); setMe(null); }} />;
}

function LoginForm({ onLogin }: { onLogin: (me: Me) => void }) {
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
