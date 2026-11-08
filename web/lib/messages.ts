import { API } from "./messages/api";
import { SURVEY } from "./messages/survey";
import { UI } from "./messages/ui";

/** Todas las traducciones: "texto en español" → [inglés, francés]. */
export const MESSAGES: Record<string, [string, string]> = { ...SURVEY, ...API, ...UI };
