"use client";

import { useEffect, useRef, useState } from "react";
import { api, ROLE_LABEL, type Me, type Role, type User } from "@/lib/api";
import { locale, useI18n } from "@/lib/i18n";

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { t } = useI18n();
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className="modal" style={{ width: wide ? "min(820px, calc(100vw - 32px))" : undefined }} onClose={onClose}>
      <header>
        <h2>{title}</h2>
        <button type="button" className="ghost" onClick={() => ref.current?.close()} aria-label={t("Cerrar")}>✕</button>
      </header>
      <div className="body">{children}</div>
    </dialog>
  );
}

export function PasswordDialog({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const { t } = useI18n();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== repeat) return setMessage({ ok: false, text: t("Las contraseñas nuevas no coinciden.") });
    try {
      await api.changePassword(current, next);
      setCurrent(""); setNext(""); setRepeat("");
      setMessage({ ok: true, text: t("Contraseña cambiada. Se cerraron tus otras sesiones.") });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <Modal title={t("Cambiar contraseña")} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label>{t("Contraseña actual")}<input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
        <label>{t("Nueva (mínimo 10 caracteres)")}<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <label>{t("Repite la nueva")}<input type="password" autoComplete="new-password" required value={repeat} onChange={(e) => setRepeat(e.target.value)} /></label>
        {message && <p className={message.ok ? "ok" : "error"} role="status">{message.text}</p>}
        <button type="submit">{t("Guardar")}</button>
      </form>
    </Modal>
  );
}

const ROLES = Object.keys(ROLE_LABEL) as Role[];

export function UsersDialog({ me, onClose }: { me: Me; onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ email: "", name: "", role: "viewer" as Role, password: "" });
  const { t } = useI18n();

  const load = () => api.users().then(setUsers).catch((err) => setError((err as Error).message));
  useEffect(() => { load(); }, []);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    await run(async () => {
      await api.createUser(draft);
      setDraft({ email: "", name: "", role: "viewer", password: "" });
    });
  }

  function resetPassword(u: User) {
    const password = window.prompt(t("Nueva contraseña para {email} (mínimo 10 caracteres):", { email: u.email }));
    if (password) run(() => api.updateUser(u.id!, { password }));
  }

  return (
    <Modal title={t("Usuarios")} onClose={onClose} wide>
      <table className="users">
        <thead><tr><th>{t("Nombre")}</th><th>{t("Correo")}</th><th>{t("Rol")}</th><th>{t("Último acceso")}</th><th /></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ opacity: u.active ? 1 : 0.55 }}>
              <td>{u.name}{u.id === me.id && <span className="muted"> {t("(tú)")}</span>}</td>
              <td className="email">{u.email}</td>
              <td className="role">
                <select value={u.role} aria-label={t("Rol de {email}", { email: u.email })} onChange={(e) => run(() => api.updateUser(u.id!, { role: e.target.value as Role }))}>
                  {ROLES.map((r) => <option key={r} value={r}>{t(ROLE_LABEL[r])}</option>)}
                </select>
              </td>
              <td className="muted" data-label={t("Último acceso")}>{u.lastLoginAt ? new Date(u.lastLoginAt).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : t("nunca")}</td>
              <td className="actions">
                <button type="button" className="ghost" onClick={() => resetPassword(u)}>{t("Contraseña")}</button>
                {u.id !== me.id && (
                  <button type="button" className="ghost" onClick={() => run(() => api.updateUser(u.id!, { active: !u.active }))}>
                    {u.active ? t("Desactivar") : t("Activar")}
                  </button>
                )}
                {u.id !== me.id && (
                  <button type="button" className="ghost danger" onClick={() => window.confirm(t("¿Borrar la cuenta de {email}?", { email: u.email })) && run(() => api.deleteUser(u.id!))}>{t("Borrar")}</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="error" role="alert">{error}</p>}
      <h3>{t("Agregar cuenta")}</h3>
      <form className="row" onSubmit={add}>
        <input placeholder={t("Nombre")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input type="email" required placeholder={t("Correo")} value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
        <select value={draft.role} aria-label={t("Rol")} onChange={(e) => setDraft({ ...draft, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r} value={r}>{t(ROLE_LABEL[r])}</option>)}
        </select>
        <input type="password" required minLength={10} autoComplete="new-password" placeholder={t("Contraseña inicial")} value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
        <button type="submit">{t("Agregar")}</button>
      </form>
      <p className="muted" style={{ fontSize: 12 }}>
        {t("Lector: ve el tablero. Analista: además agrega objetivos y contesta cuestionarios. Administrador: además borra objetivos y administra cuentas.")}
      </p>
    </Modal>
  );
}
