"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api, KIND_LABEL, type TargetKind, type TargetSearch, type TargetSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { PHONE, useMediaQuery } from "@/lib/useMediaQuery";
import { KIND_COLOR } from "./Analytics";

const KINDS = Object.keys(KIND_LABEL) as TargetKind[];
const PAGE = 50;
const RECENT_KEY = "minos.recentTargets";
const RECENT_MAX = 6;

/** Minúsculas y sin acentos, igual que la búsqueda del servidor, para saber si lo buscado está en el nombre. */
const fold = (s: string) => s.normalize("NFD").replace(/\p{Mn}/gu, "").toLowerCase();
const words = (s: string) => fold(s).split(/[^\p{L}\p{N}@#]+/u).filter(Boolean);
function matches(text: string, query: string[]) {
  const w = words(text);
  return query.every((q) => w.some((x) => x.startsWith(q)));
}

function readRecent(): TargetSummary[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => x && typeof x.id === "string" && typeof x.name === "string") : [];
  } catch {
    return [];
  }
}

function saveRecent(list: TargetSummary[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    /* sin almacenamiento */
  }
}

/** Quita un objetivo de los recientes (por ejemplo, si se borró). */
export function forgetRecentTarget(id: string) {
  saveRecent(readRecent().filter((x) => x.id !== id));
}

/**
 * Selector de objetivo del tablero. Busca en el servidor (nombre y alias, sin importar acentos), filtra por tipo,
 * agrupa los resultados por tipo y carga más al bajar, así que funciona igual con diez objetivos que con miles.
 */
export function TargetPicker({ selected, onSelect, refreshKey = 0 }: {
  selected: TargetSummary | null;
  onSelect: (t: TargetSummary) => void;
  /** Cambia cuando se edita, da de baja o borra un objetivo, para volver a buscar. */
  refreshKey?: number;
}) {
  const { t, nf } = useI18n();
  const phone = useMediaQuery(PHONE);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<TargetKind | "">("");
  const [inactive, setInactive] = useState(false);
  const [result, setResult] = useState<TargetSearch | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<TargetSummary[]>([]);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  const id = useId();

  const status = inactive ? "all" : "active";
  const query = useMemo(() => words(q), [q]);
  const showRecent = open && !query.length && !kind && recent.length > 0;

  const load = useCallback(async (offset: number) => {
    request.current?.abort();
    const ctrl = new AbortController();
    request.current = ctrl;
    setLoading(true);
    setError("");
    try {
      const page = await api.searchTargets({ q: q.trim(), kind, status, limit: PAGE, offset }, ctrl.signal);
      setResult((prev) => (offset && prev ? { ...page, items: [...prev.items, ...page.items] } : page));
      if (!offset) setActive(0);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      if (request.current === ctrl) setLoading(false);
    }
  }, [q, kind, status]);

  // Busca al abrir y al cambiar el texto (con una pausa corta para no pedir en cada tecla), el tipo o el estado.
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => load(0), q ? 200 : 0);
    return () => clearTimeout(timer);
  }, [open, load, refreshKey]);

  useEffect(() => () => request.current?.abort(), []);

  const items = result?.items ?? [];
  const hasMore = !!result && items.length < result.total;
  // Opciones en el orden en que se ven: primero los recientes (sin búsqueda), luego los resultados.
  const options = useMemo(() => [
    ...(showRecent ? recent.map((x) => ({ key: `r-${x.id}`, target: x })) : []),
    ...items.map((x) => ({ key: `i-${x.id}`, target: x })),
  ], [showRecent, recent, items]);

  // Carga la siguiente página al llegar al final de la lista.
  useEffect(() => {
    const el = sentinel.current;
    if (!open || !el || !hasMore) return;
    const obs = new IntersectionObserver((e) => {
      if (e[0].isIntersecting && !loading) load(items.length);
    }, { root: list.current, rootMargin: "120px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [open, hasMore, loading, items.length, load]);

  // Cierra al tocar fuera (en teléfono ocupa toda la pantalla y se cierra con su botón).
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  // Ctrl+K o ⌘K abren el selector desde cualquier parte del tablero.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        show();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    if (phone) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = prev; };
    }
  }, [open, phone]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function show() {
    setRecent(readRecent());
    setOpen(true);
  }

  function close(focusTrigger = true) {
    setOpen(false);
    if (focusTrigger) trigger.current?.focus();
  }

  function choose(x: TargetSummary) {
    saveRecent([x, ...readRecent().filter((r) => r.id !== x.id)]);
    onSelect(x);
    setQ("");
    close();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Home" && e.ctrlKey) { e.preventDefault(); setActive(0); }
    else if (e.key === "End" && e.ctrlKey) { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const o = options[active];
      if (o) choose(o.target);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  }

  const kindLabel = (k: TargetKind) => t(KIND_LABEL[k]);
  const allCount = result ? KINDS.reduce((n, k) => n + (result.kinds[k] ?? 0), 0) : null;

  function row(o: { key: string; target: TargetSummary }, index: number) {
    const x = o.target;
    // Si lo buscado no está en el nombre, se muestra el alias por el que salió.
    const alias = query.length && !matches(x.name, query) ? x.aliases?.find((a) => matches(a, query)) : undefined;
    return (
      <div key={o.key} id={`${id}-${o.key}`} role="option" data-index={index}
        aria-selected={index === active} className={`opt${index === active ? " active" : ""}${x.id === selected?.id ? " current" : ""}`}
        onPointerMove={() => setActive(index)} onClick={() => choose(x)}>
        <span className="kind-dot" style={{ background: KIND_COLOR[x.kind] }} aria-hidden />
        <span className="name">
          {x.name}
          {alias && <small className="alias">{t("alias: {alias}", { alias })}</small>}
        </span>
        {!x.enabled && <span className="off">{t("de baja")}</span>}
        {o.key.startsWith("r-") && <span className="meta">{kindLabel(x.kind)}</span>}
        {x.id === selected?.id && <span className="check" aria-label={t("Seleccionado")}>✓</span>}
      </div>
    );
  }

  // Resultados agrupados por tipo (el servidor ya los manda ordenados por tipo).
  const groups: { kind: TargetKind; rows: React.ReactNode[] }[] = [];
  const offset = showRecent ? recent.length : 0;
  items.forEach((x, i) => {
    let g = groups[groups.length - 1];
    if (!g || g.kind !== x.kind) groups.push((g = { kind: x.kind, rows: [] }));
    g.rows.push(row(options[offset + i], offset + i));
  });

  return (
    <div className="target-picker" ref={root}>
      <button ref={trigger} type="button" className="trigger" aria-haspopup="dialog" aria-expanded={open}
        onClick={() => (open ? close(false) : show())} title={t("Buscar objetivo (Ctrl+K)")}>
        {selected ? (
          <>
            <span className="kind-dot" style={{ background: KIND_COLOR[selected.kind] }} aria-hidden />
            <span className="name">{selected.name}</span>
            <span className="meta">{kindLabel(selected.kind)}{selected.enabled ? "" : ` ${t("(de baja)")}`}</span>
          </>
        ) : <span className="name muted">{t("Elegir objetivo")}</span>}
        <span className="caret" aria-hidden>▾</span>
      </button>

      {open && (
        <div className="picker-panel" role="dialog" aria-label={t("Elegir objetivo")} onKeyDown={onKey}>
          <div className="picker-head">
            <input ref={input} type="search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={t("Buscar por nombre o alias…")} aria-label={t("Buscar objetivo")}
              role="combobox" aria-expanded aria-controls={`${id}-list`} aria-autocomplete="list"
              aria-activedescendant={options[active] ? `${id}-${options[active].key}` : undefined}
              autoComplete="off" spellCheck={false} enterKeyHint="go" />
            {phone && <button type="button" className="ghost" onClick={() => close()}>{t("Cerrar")}</button>}
          </div>
          <div className="kinds" role="group" aria-label={t("Tipo")}>
            <button type="button" className={kind === "" ? "on" : "ghost"} aria-pressed={kind === ""} onClick={() => setKind("")}>
              {t("Todos")}{allCount != null && <span className="count">{nf.format(allCount)}</span>}
            </button>
            {KINDS.map((k) => (
              <button key={k} type="button" className={kind === k ? "on" : "ghost"} aria-pressed={kind === k}
                onClick={() => setKind(kind === k ? "" : k)} disabled={!!result && !result.kinds[k] && kind !== k}>
                <span className="kind-dot" style={{ background: KIND_COLOR[k] }} aria-hidden />{kindLabel(k)}
                {result && <span className="count">{nf.format(result.kinds[k] ?? 0)}</span>}
              </button>
            ))}
          </div>
          <label className="check inactive">
            <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
            {t("Incluir dados de baja")}
          </label>

          <div className="picker-list" id={`${id}-list`} role="listbox" aria-label={t("Objetivos")} ref={list}>
            {showRecent && (
              <div role="group" aria-label={t("Recientes")}>
                <div className="group" aria-hidden>{t("Recientes")}</div>
                {recent.map((x, i) => row(options[i], i))}
              </div>
            )}
            {groups.map((g) => (
              <div key={g.kind} role="group" aria-label={kindLabel(g.kind)}>
                <div className="group" aria-hidden>{kindLabel(g.kind)}</div>
                {g.rows}
              </div>
            ))}
            {result && !items.length && !loading && (
              <p className="empty muted">{q.trim() ? t("Sin resultados para «{q}».", { q: q.trim() }) : t("No hay objetivos con este filtro.")}</p>
            )}
            {error && <p className="error">{error}</p>}
            {hasMore && <div ref={sentinel} className="more muted">{loading ? t("Cargando…") : (
              <button type="button" className="link" onClick={() => load(items.length)}>{t("Mostrar más")}</button>
            )}</div>}
          </div>
          <div className="picker-foot muted" aria-live="polite">
            {loading && !items.length ? t("Buscando…") : result
              ? t("{shown} de {total}", { shown: items.length, total: result.total }) : ""}
            {!phone && <span className="keys">{t("↑↓ para moverse · Enter para abrir · Esc para cerrar")}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
