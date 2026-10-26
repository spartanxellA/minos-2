"use client";

import { useState } from "react";
import { api, KIND_LABEL, type Target, type TargetKind } from "@/lib/api";

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function NewTargetForm({ onCreated, onCancel }: { onCreated: (t: Target) => void; onCancel?: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<TargetKind>("Person");
  const [aliases, setAliases] = useState("");
  const [excluded, setExcluded] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const t = await api.createTarget({
        name, kind, aliases: split(aliases), keywords: [], excludedTerms: split(excluded), handles: {},
      });
      setName(""); setAliases(""); setExcluded(""); setError(null);
      onCreated(t);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="new" onSubmit={submit}>
      <input placeholder="Nombre a monitorear" aria-label="Nombre a monitorear" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
      <select aria-label="Tipo" value={kind} onChange={(e) => setKind(e.target.value as TargetKind)}>
        {Object.entries(KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      <input aria-label="Alias" placeholder="Alias (separados por coma)" value={aliases} onChange={(e) => setAliases(e.target.value)} />
      <input aria-label="Excluir" placeholder="Excluir (homónimos)" value={excluded} onChange={(e) => setExcluded(e.target.value)} />
      <div className="actions">
        <button type="submit">Agregar</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancelar</button>}
      </div>
      {error && <span className="error">{error}</span>}
    </form>
  );
}
