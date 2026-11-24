import type { TargetKind } from "./api";
import { locale, msg } from "./i18n";

export const SENT = [
  { key: "positive", label: msg("Positivo"), color: "#2e7d32" },
  { key: "neutral", label: msg("Neutro"), color: "#8a94a0" },
  { key: "negative", label: msg("Negativo"), color: "#d32f2f" },
] as const;

// Sin rojo ni verde, que ya significan sentimiento y nivel de riesgo.
export const KIND_COLOR: Record<TargetKind, string> = {
  Person: "#1668b7", Company: "#e07b00", Institution: "#2a9d8f", GovernmentArea: "#8e5bd0", Country: "#c2185b",
};

/** "2026" | "2026-03" | "2026-03-15" como texto para ejes y títulos. */
export function periodLabel(p: string, long = false) {
  const [y, m, d] = p.split("-").map(Number);
  if (!m) return p;
  if (d) return new Date(y, m - 1, d).toLocaleString(locale(), { day: "numeric", month: "short", year: long ? "numeric" : undefined });
  return new Date(y, m - 1, 1).toLocaleString(locale(), { month: long ? "long" : "short", year: long ? "numeric" : "2-digit" });
}

/** Primer mes de los últimos n, contando el actual. */
export function monthsAgo(n: number) {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - (n - 1));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Franjas de nivel (bajo, medio, alto) al fondo de las gráficas del índice. */
export const riskBands = {
  silent: true, itemStyle: { opacity: 0.06 }, data: [
    [{ yAxis: 0, itemStyle: { color: "#2e7d32" } }, { yAxis: 25 }],
    [{ yAxis: 25, itemStyle: { color: "#c9a800" } }, { yAxis: 50 }],
    [{ yAxis: 50, itemStyle: { color: "#d32f2f" } }, { yAxis: 100 }],
  ],
} as const;
