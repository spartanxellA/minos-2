"use client";

import { useState } from "react";
import { api, KIND_LABEL, type Target, type TargetKind } from "@/lib/api";

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function NewTargetForm({ onCreated }: { onCreated: (t: Target) => void }) {
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
      <input placeholder="Nombre a monitorear" value={name} onChange={(e) => setName(e.target.value)} />
      <select value={kind} onChange={(e) => setKind(e.target.value as TargetKind)}>
        {Object.entries(KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      <input placeholder="Alias (separados por coma)" value={aliases} onChange={(e) => setAliases(e.target.value)} />
      <input placeholder="Excluir (homónimos)" value={excluded} onChange={(e) => setExcluded(e.target.value)} />
      <button type="submit">Agregar</button>
      {error && <span style={{ color: "var(--neg)" }}>{error}</span>}
    </form>
  );
}
