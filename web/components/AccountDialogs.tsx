"use client";

import { useEffect, useRef, useState } from "react";
import { api, ROLE_LABEL, type Me, type Role, type User } from "@/lib/api";

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className="modal" style={{ width: wide ? "min(820px, calc(100vw - 32px))" : undefined }} onClose={onClose}>
      <header>
        <h2>{title}</h2>
        <button type="button" className="ghost" onClick={() => ref.current?.close()} aria-label="Cerrar">✕</button>
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== repeat) return setMessage({ ok: false, text: "Las contraseñas nuevas no coinciden." });
    try {
      await api.changePassword(current, next);
      setCurrent(""); setNext(""); setRepeat("");
      setMessage({ ok: true, text: "Contraseña cambiada. Se cerraron tus otras sesiones." });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <Modal title="Cambiar contraseña" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label>Contraseña actual<input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
        <label>Nueva (mínimo 10 caracteres)<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <label>Repite la nueva<input type="password" autoComplete="new-password" required value={repeat} onChange={(e) => setRepeat(e.target.value)} /></label>
        {message && <p className={message.ok ? "ok" : "error"} role="status">{message.text}</p>}
        <button type="submit">Guardar</button>
      </form>
    </Modal>
  );
}

const ROLES = Object.keys(ROLE_LABEL) as Role[];

export function UsersDialog({ me, onClose }: { me: Me; onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ email: "", name: "", role: "viewer" as Role, password: "" });

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
    const password = window.prompt(`Nueva contraseña para ${u.email} (mínimo 10 caracteres):`);
    if (password) run(() => api.updateUser(u.id!, { password }));
  }

  return (
    <Modal title="Usuarios" onClose={onClose} wide>
      <table>
        <thead><tr><th>Nombre</th><th>Correo</th><th>Rol</th><th>Último acceso</th><th /></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ opacity: u.active ? 1 : 0.55 }}>
              <td>{u.name}{u.id === me.id && <span className="muted"> (tú)</span>}</td>
              <td>{u.email}</td>
              <td>
                <select value={u.role} aria-label={`Rol de ${u.email}`} onChange={(e) => run(() => api.updateUser(u.id!, { role: e.target.value as Role }))}>
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
              </td>
              <td className="muted">{u.lastLoginAt ? new Date(u.lastLoginAt).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" }) : "nunca"}</td>
              <td className="actions">
                <button type="button" className="ghost" onClick={() => resetPassword(u)}>Contraseña</button>
                {u.id !== me.id && (
                  <button type="button" className="ghost" onClick={() => run(() => api.updateUser(u.id!, { active: !u.active }))}>
                    {u.active ? "Desactivar" : "Activar"}
                  </button>
                )}
                {u.id !== me.id && (
                  <button type="button" className="ghost danger" onClick={() => window.confirm(`¿Borrar la cuenta de ${u.email}?`) && run(() => api.deleteUser(u.id!))}>Borrar</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="error" role="alert">{error}</p>}
      <h3>Agregar cuenta</h3>
      <form className="row" onSubmit={add}>
        <input placeholder="Nombre" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input type="email" required placeholder="Correo" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
        <select value={draft.role} aria-label="Rol" onChange={(e) => setDraft({ ...draft, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        <input type="password" required minLength={10} autoComplete="new-password" placeholder="Contraseña inicial" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
        <button type="submit">Agregar</button>
      </form>
      <p className="muted" style={{ fontSize: 12 }}>
        Lector: ve el tablero. Analista: además agrega objetivos y contesta cuestionarios. Administrador: además borra objetivos y administra cuentas.
      </p>
    </Modal>
  );
}
