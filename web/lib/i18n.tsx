"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { MESSAGES } from "./messages";

/**
 * Idiomas del tablero. Los textos se escriben en español dentro del código (t("Guardar")) y messages.ts trae su
 * traducción al inglés y al francés; lo que no esté ahí se queda en español. `npm run i18n:check` revisa que no
 * falte ninguno.
 */
export type Lang = "es" | "en" | "fr";
export const LANGS: Record<Lang, string> = { es: "Español", en: "English", fr: "Français" };
const LOCALES: Record<Lang, string> = { es: "es-MX", en: "en-US", fr: "fr-FR" };
const STORAGE_KEY = "minos.lang";
const COLUMN: Record<Exclude<Lang, "es">, 0 | 1> = { en: 0, fr: 1 };

type Vars = Record<string, string | number>;

// Idioma activo para el código que no es un componente (api.ts, funciones de formato). El proveedor lo cambia antes
// de volver a pintar, así que todo lo que se pinta después ya sale en el idioma nuevo.
let current: Lang = "es";

/** Marca un texto fijo (p. ej. en una tabla de etiquetas) para que `npm run i18n:check` lo encuentre; se traduce
 * después con t(). */
export const msg = (es: string) => es;

export const isLang = (v: unknown): v is Lang => v === "es" || v === "en" || v === "fr";
export const currentLang = () => current;
export const locale = () => LOCALES[current];

function fill(text: string, vars?: Vars) {
  if (!vars) return text;
  const nf = new Intl.NumberFormat(locale());
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? (typeof vars[k] === "number" ? nf.format(vars[k] as number) : String(vars[k])) : m));
}

/** Texto de la interfaz. Las llaves {nombre} se llenan con vars (los números salen con el formato del idioma). */
export function translate(es: string, vars?: Vars, lang: Lang = current): string {
  if (lang === "es") return fill(es, vars);
  const row = MESSAGES[es];
  return fill(row ? row[COLUMN[lang]] : es, vars);
}

// Plantillas para textos que llegan ya armados del servidor ("El índice subió 18 puntos en 24 horas…"): cada {x}
// captura un pedazo, que a su vez se traduce si es un texto conocido (p. ej. un rol o un tipo de lista).
type Pattern = { re: RegExp; names: string[]; key: string };
let patterns: Pattern[] | null = null;
function compiled(): Pattern[] {
  if (patterns) return patterns;
  const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  patterns = Object.keys(MESSAGES).filter((k) => /\{\w+\}/.test(k)).map((key) => {
    const names: string[] = [];
    const source = key.split(/(\{\w+\})/).map((part) => {
      const m = /^\{(\w+)\}$/.exec(part);
      if (!m) return escape(part);
      names.push(m[1]);
      return "([\\s\\S]*?)";
    }).join("");
    return { re: new RegExp(`^${source}$`), names, key };
  }).sort((a, b) => b.key.length - a.key.length); // la plantilla más específica primero
  return patterns;
}

/**
 * Texto que viene del servidor (mensajes de error, alertas, etiquetas). Si no es uno conocido se deja tal cual:
 * puede ser un dato (el nombre de una lista, un texto de una mención) que no se traduce.
 */
export function translateApi(text: string | null | undefined, lang: Lang = current): string {
  if (!text || lang === "es") return text ?? "";
  const row = MESSAGES[text];
  if (row) return row[COLUMN[lang]];
  // Varios mensajes juntos ("Faltan datos. Revisa el archivo.") se traducen por partes.
  for (const p of compiled()) {
    const m = p.re.exec(text);
    if (!m) continue;
    const vars: Vars = {};
    p.names.forEach((n, i) => { vars[n] = MESSAGES[m[i + 1]] ? MESSAGES[m[i + 1]][COLUMN[lang]] : m[i + 1]; });
    return MESSAGES[p.key][COLUMN[lang]].replace(/\{(\w+)\}/g, (all, k: string) => (k in vars ? String(vars[k]) : all));
  }
  return text;
}

function stored(): Lang | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isLang(v) ? v : null;
  } catch {
    return null;
  }
}

function fromBrowser(): Lang {
  for (const l of typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]) {
    const code = l.slice(0, 2).toLowerCase();
    if (isLang(code)) return code;
  }
  return "es";
}

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (es: string, vars?: Vars) => string;
  tApi: (text: string | null | undefined) => string;
  /** "es-MX", "en-US" o "fr-FR", para fechas y números. */
  locale: string;
  nf: Intl.NumberFormat;
}

const Context = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setState] = useState<Lang>("es");

  const setLang = useCallback((next: Lang) => {
    current = next;
    setState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* sin almacenamiento: dura lo que dure la pestaña */
    }
  }, []);

  // Se lee en el navegador (no en el servidor de Next) para no pintar distinto en la hidratación.
  useEffect(() => {
    const initial = stored() ?? fromBrowser();
    current = initial;
    setState(initial);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = translate("minOS 2.0 · Riesgo reputacional", undefined, lang);
  }, [lang]);

  const value = useMemo<I18n>(() => ({
    lang, setLang,
    t: (es, vars) => translate(es, vars, lang),
    tApi: (text) => translateApi(text, lang),
    locale: LOCALES[lang],
    nf: new Intl.NumberFormat(LOCALES[lang]),
  }), [lang, setLang]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useI18n fuera de I18nProvider");
  return ctx;
}

/** Selector de idioma; onChange avisa para guardarlo también en la cuenta. */
export function LanguageSelect({ onChange, className }: { onChange?: (lang: Lang) => void; className?: string }) {
  const { lang, setLang, t } = useI18n();
  return (
    <select className={className ?? "lang"} value={lang} aria-label={t("Idioma")} title={t("Idioma")}
      onChange={(e) => {
        const next = e.target.value as Lang;
        setLang(next);
        onChange?.(next);
      }}>
      {(Object.keys(LANGS) as Lang[]).map((l) => <option key={l} value={l} lang={l}>{LANGS[l]}</option>)}
    </select>
  );
}
