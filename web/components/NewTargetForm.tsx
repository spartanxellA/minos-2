"use client";

import { useState } from "react";
import { api, KIND_LABEL, type Target, type TargetKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function NewTargetForm({ onCreated, onCancel }: { onCreated: (t: Target) => void; onCancel?: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<TargetKind>("Person");
  const [aliases, setAliases] = useState("");
  const [excluded, setExcluded] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { t: tr } = useI18n();

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
      <input placeholder={tr("Nombre a monitorear")} aria-label={tr("Nombre a monitorear")} autoFocus value={name} onChange={(e) => setName(e.target.value)} />
      <select aria-label={tr("Tipo")} value={kind} onChange={(e) => setKind(e.target.value as TargetKind)}>
        {Object.entries(KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{tr(label)}</option>)}
      </select>
      <input aria-label={tr("Alias")} placeholder={tr("Alias (separados por coma)")} value={aliases} onChange={(e) => setAliases(e.target.value)} />
      <input aria-label={tr("Excluir")} placeholder={tr("Excluir (homónimos)")} value={excluded} onChange={(e) => setExcluded(e.target.value)} />
      <div className="actions">
        <button type="submit">{tr("Agregar")}</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>{tr("Cancelar")}</button>}
      </div>
      {error && <span className="error">{error}</span>}
    </form>
  );
}
