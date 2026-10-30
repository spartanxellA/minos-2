export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5080";
export const WS_URL = API_URL.replace(/^http/, "ws");

export type TargetKind = "Person" | "Company" | "Institution" | "GovernmentArea" | "Country";

export interface Target {
  id: string;
  name: string;
  kind: TargetKind;
  aliases: string[];
  keywords: string[];
  excludedTerms: string[];
  handles: Record<string, string>;
  enabled: boolean;
  /** AAAA-MM-DD o AAAA; afina la revisión en listas negras. */
  birthDate?: string | null;
  nationality?: string | null;
  /** "rfc", "curp", "pasaporte" → valor. */
  identifiers?: Record<string, string>;
  createdAt?: string;
  updatedAt?: string | null;
  /** Baja lógica: enabled=false, con fecha, quién y por qué. */
  deactivatedAt?: string | null;
  deactivatedByEmail?: string | null;
  deactivationReason?: string | null;
}

export type TargetInput = Omit<Target, "id" | "enabled" | "createdAt" | "updatedAt" | "deactivatedAt" | "deactivatedByEmail" | "deactivationReason">;

export interface Risk {
  targetId: string;
  at: string;
  index: number;
  level: "Low" | "Medium" | "High";
  label: string;
  color: string;
  mediaScore: number;
  surveyScore: number | null;
  negativity: number;
  severity: number;
  volumeAnomaly: number;
  mentions: number;
  positive: number;
  negative: number;
  neutral: number;
  topDrivers: string[];
  /** Puntos que sumaron las coincidencias confirmadas en listas negras. */
  watchlistImpact: number;
}

export interface Mention {
  id: string;
  source: string;
  url: string;
  author: string;
  authorName: string | null;
  followers: number;
  publishedAt: string;
  text: string;
  sentiment: Sentiment;
  score: number;
  severe: boolean;
  topic: string | null;
  summary: string | null;
  interactions: number;
  /** Lo cambió un analista; originalSentiment es lo que dijo el análisis automático. */
  corrected: boolean;
  originalSentiment: Sentiment | null;
  correctedBy: string | null;
  /** Lugar asignado para el mapa ("Monterrey, Nuevo León") y de qué pista salió. */
  place?: string | null;
  placeMethod?: GeoMethod | null;
}

export type Sentiment = "positive" | "negative" | "neutral";

export interface Breakdown {
  bySourceAndSentiment: { source: string; sentiment: string; count: number }[];
  influencers: { author: string; followers: number; mentions: number; negative: number }[];
  topics: { topic: string; count: number }[];
}

export interface Alert {
  id?: number | null;
  kind: string;
  title: string;
  message: string;
  mentionId?: string | null;
  at?: string | null;
}

export interface SurveyOption {
  value: string;
  label: string;
  weight: number | null;
}

export interface SurveyQuestion {
  id: string;
  number: number;
  text: string;
  subtext: string | null;
  type: string;
  required: boolean;
  options: SurveyOption[];
}

export interface SurveySection {
  id: string;
  name: string;
  theme: string;
  color: string;
  weight: number;
  order: number;
  description: string;
  questions: SurveyQuestion[];
}

export interface Survey {
  id: string;
  name: string;
  description: string;
  scored: boolean;
  sections: SurveySection[];
}

export interface SurveyResponse {
  id: string;
  targetId: string;
  surveyId: string;
  submittedAt: string;
  score: number | null;
  level: "Low" | "Medium" | "High" | null;
  sectionValues: Record<string, number>;
  answers: Record<string, string>;
}

/** El cuestionario de riesgo de minOS 1.6; el de perfil (PDSurvey) no puntúa. */
export const RISK_SURVEY = "RASurvey";

/** Umbrales heredados (≤ 25 bajo, ≤ 50 medio), los mismos que usa el backend. */
export function riskLevel(score: number) {
  if (score <= 25) return { label: "Riesgo bajo", color: "#2e7d32" };
  if (score <= 50) return { label: "Riesgo medio", color: "#c9a800" };
  return { label: "Riesgo alto", color: "#d32f2f" };
}

export interface SourceStatus {
  source: string;
  configured: boolean;
  lastRunAt: string | null;
  lastMentionAt: string | null;
  mentionsLastDay: number;
  errors: { targetId: string; targetName: string; at: string | null; error: string }[];
}

export interface SourcesStatus {
  sources: SourceStatus[];
  channels: { channel: string; configured: boolean }[];
}

export type MatchStatus = "pending" | "confirmed" | "dismissed";

export interface ScreeningMatch {
  id: number;
  targetId: string;
  targetName: string | null;
  source: string;
  sourceName: string;
  category: string;
  categoryLabel: string;
  listedName: string;
  matchedName: string;
  score: number;
  strength: "possible" | "strong";
  reasons: string[];
  entry: {
    kind?: string; name?: string; aliases?: string[]; birthDates?: string[]; nationalities?: string[];
    identifiers?: string[]; programs?: string[]; listedOn?: string | null; status?: string | null;
    url?: string | null; notes?: string | null;
  };
  status: MatchStatus;
  active: boolean;
  firstSeenAt: string;
  lastSeenAt: string;
  reviewedAt: string | null;
  reviewedByEmail: string | null;
  reviewNote: string | null;
}

export interface Screening {
  targetId: string;
  status: "not_screened" | "clear" | "possible" | "confirmed";
  screenedAt: string | null;
  pending: number;
  confirmed: number;
  matches: ScreeningMatch[];
  lists: number;
  disclaimer: string;
}

export interface Watchlist {
  slug: string;
  name: string;
  publisher: string | null;
  category: string;
  categoryLabel: string;
  custom: boolean;
  enabled: boolean;
  configured: boolean;
  infoUrl: string | null;
  license: string | null;
  entryCount: number;
  lastCheckedAt: string | null;
  lastChangedAt: string | null;
  lastError: string | null;
  uploadedBy: string | null;
}

export const WATCHLIST_CATEGORIES: Record<string, string> = {
  pep: "Persona políticamente expuesta", sanctions: "Sanciones", tax: "Fiscal (SAT)", debarment: "Inhabilitación", other: "Otra",
};

export const SOURCE_LABEL: Record<string, string> = {
  rss: "Noticias", x: "X", youtube: "YouTube", bluesky: "Bluesky", "bluesky-live": "Bluesky en vivo", reddit: "Reddit",
  facebook: "Facebook", instagram: "Instagram", demo: "Demo",
};

export type Role = "viewer" | "analyst" | "admin";

export interface User {
  id: string | null;
  email: string;
  name: string;
  role: Role;
  roleLabel: string;
  active: boolean;
  lastLoginAt?: string | null;
}

export interface Me extends User {
  authMode: "local" | "off";
}

export interface AuditEvent {
  id: number;
  at: string;
  actorId: string | null;
  actorEmail: string | null;
  actorRole: Role | null;
  action: string;
  actionLabel: string;
  success: boolean;
  entityType: "user" | "target" | "watchlist" | null;
  entityId: string | null;
  entityLabel: string | null;
  /** Campo → [antes, después]. */
  changes: Record<string, [unknown, unknown]> | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
  userAgent: string | null;
}

export interface AuditPage {
  events: AuditEvent[];
  nextBefore: number | null;
  actions: Record<string, string>;
}

export interface AuditFilters {
  action?: string;
  actor?: string;
  entityType?: string;
  entityId?: string;
  success?: boolean;
  since?: string;
  until?: string;
  q?: string;
}

export function auditQuery(filters: AuditFilters, extra: Record<string, string | number | undefined> = {}) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters, ...extra })) {
    if (v !== undefined && v !== "") params.set(k, String(v));
  }
  return params.toString();
}

export const auditCsvUrl = (filters: AuditFilters) => `${API_URL}/api/audit/export.csv?${auditQuery(filters)}`;

export const ROLE_LABEL: Record<Role, string> = { viewer: "Lector", analyst: "Analista", admin: "Administrador" };
const ROLE_RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 };
export const can = (user: Pick<User, "role">, role: Role) => ROLE_RANK[user.role] >= ROLE_RANK[role];

/** La sesión venció o se cerró en otro lado: el tablero vuelve a la pantalla de inicio de sesión. */
export const UNAUTHORIZED_EVENT = "minos:unauthorized";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

const FIELD_LABEL: Record<string, string> = {
  name: "El nombre", category: "El tipo", csv: "El archivo", note: "La nota", reason: "El motivo",
  birthDate: "La fecha de nacimiento", email: "El correo", password: "La contraseña",
};

/** Los 422 de validación llegan como lista ({loc, type, ctx}); se traduce el primero a una frase. */
function validationMessage(errors: { loc?: (string | number)[]; type?: string; msg?: string; ctx?: Record<string, unknown> }[]) {
  const e = errors[0];
  if (!e) return null;
  const key = String(e.loc?.at(-1) ?? "");
  const field = FIELD_LABEL[key] ?? (key && key !== "body" ? `El campo «${key}»` : "Los datos enviados");
  const n = (v: unknown) => new Intl.NumberFormat("es-MX").format(Number(v));
  switch (e.type) {
    case "missing": return `${field} es obligatorio.`;
    case "string_too_short": return Number(e.ctx?.min_length) <= 1 ? `${field} está vacío.` : `${field} es muy corto (mínimo ${n(e.ctx?.min_length)} caracteres).`;
    case "string_too_long": return `${field} es muy grande (máximo ${n(e.ctx?.max_length)} caracteres).`;
    case "string_pattern_mismatch": return `${field} no tiene el formato esperado.`;
    case "literal_error": return `${field} no es una opción válida.`;
    case "json_invalid": return "Los datos enviados no son válidos.";
    default: return `${field}: ${e.msg ?? "valor no válido"}.`;
  }
}

/** Todas las llamadas llevan la cookie de sesión (HttpOnly; el JavaScript del tablero no la ve). */
async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    credentials: "include",
    ...rest,
    headers: json === undefined ? rest.headers : { "content-type": "application/json", ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? validationMessage(detail) ?? `Error ${res.status}`
      : detail?.message ?? `Error ${res.status}`;
    throw new ApiError(res.status, message, body);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const get = <T,>(path: string) => request<T>(path);

export type Granularity = "month" | "year";

export type GeoMethod = "geotag" | "profile" | "community" | "outlet" | "text";
/** "origin": de dónde es quien publica. "text": de qué lugar habla la mención. */
export type GeoBasis = "all" | "origin" | "text";

export const GEO_METHOD_LABEL: Record<GeoMethod, string> = {
  geotag: "Geoetiqueta", profile: "Perfil del autor", community: "Comunidad", outlet: "Sede del medio", text: "Lugar mencionado",
};

export interface GeoArea { code: string; name: string; count: number; negative: number }

export interface GeoPlace {
  name: string;
  country: string;
  region: string | null;
  lat: number;
  lon: number;
  precision: "point" | "city" | "region" | "country";
  count: number;
  negative: number;
}

export interface GeoOverview {
  since: string;
  until: string;
  basis: GeoBasis;
  total: number;
  located: number;
  byMethod: { method: GeoMethod; count: number }[];
  bySource: { source: string; total: number; located: number }[];
  countries: GeoArea[];
  /** Solo estados de México. */
  regions: GeoArea[];
  places: GeoPlace[];
  /** Menciones guardadas antes del mapa que todavía no se intentan ubicar. */
  pending: number;
}

export interface MentionsOverview {
  granularity: Granularity;
  timezone: string;
  /** "2026-01" por mes o "2026" por año; todos los del rango, con o sin datos. */
  periods: string[];
  ranking: {
    targetId: string; name: string; kind: TargetKind; enabled: boolean; mentions: number;
    positive: number; neutral: number; negative: number; severe: number; lastIndex: number | null;
  }[];
  byKind: { kind: TargetKind; targets: number; mentions: number; negative: number }[];
  mentionsByKind: { period: string; kind: TargetKind; count: number }[];
  mentionsByTarget: { period: string; targetId: string; count: number }[];
  riskByTarget: { period: string; targetId: string; avg: number; max: number }[];
  riskByKind: { period: string; kind: TargetKind; avg: number }[];
}

export interface OverviewFilters {
  granularity: Granularity;
  since?: string;
  until?: string;
  kind?: TargetKind | "";
  source?: string;
  top?: number;
  includeInactive?: boolean;
}

function overviewQuery(f: OverviewFilters) {
  const params = new URLSearchParams({ granularity: f.granularity });
  for (const [k, v] of Object.entries(f)) {
    if (k !== "granularity" && v !== undefined && v !== "" && v !== false) params.set(k, String(v));
  }
  return params.toString();
}

export const api = {
  targets: () => get<Target[]>("/api/targets"),
  mentionsOverview: (f: OverviewFilters) => get<MentionsOverview>(`/api/analytics/mentions?${overviewQuery(f)}`),
  risk: (id: string, hours = 24 * 7) => get<Risk[]>(`/api/targets/${id}/risk?hours=${hours}`),
  mentions: (id: string, limit = 40) => get<Mention[]>(`/api/targets/${id}/mentions?limit=${limit}`),
  breakdown: (id: string, hours = 24) => get<Breakdown>(`/api/targets/${id}/breakdown?hours=${hours}`),
  alerts: (id: string) => get<Alert[]>(`/api/targets/${id}/alerts`),
  survey: (surveyId: string) => get<Survey>(`/api/surveys/${surveyId}`),
  surveyResponses: (id: string, surveyId: string, limit = 10) =>
    get<SurveyResponse[]>(`/api/targets/${id}/survey-responses?surveyId=${surveyId}&limit=${limit}`),
  submitSurvey: (id: string, surveyId: string, answers: Record<string, string>) =>
    request<SurveyResponse>(`/api/targets/${id}/survey-responses`, { method: "POST", json: { surveyId, answers } }),
  sources: () => get<SourcesStatus>("/api/sources"),
  createTarget: (input: TargetInput) => request<Target>("/api/targets", { method: "POST", json: input }),
  updateTarget: (t: TargetInput & { id: string }) => request<Target>(`/api/targets/${t.id}`, { method: "PUT", json: t }),
  deactivateTarget: (id: string, reason: string) =>
    request<Target>(`/api/targets/${id}/deactivate`, { method: "POST", json: { reason } }),
  reactivateTarget: (id: string) => request<Target>(`/api/targets/${id}/reactivate`, { method: "POST" }),
  deleteTarget: (id: string) => request<void>(`/api/targets/${id}`, { method: "DELETE" }),

  geo: (id: string, days: number, basis: GeoBasis, source = "") =>
    get<GeoOverview>(`/api/targets/${id}/geo?${new URLSearchParams({ days: String(days), basis, ...(source ? { source } : {}) })}`),
  locatePending: (id: string) => request<{ reviewed: number }>(`/api/targets/${id}/geo/locate`, { method: "POST" }),

  correctSentiment: (mentionId: string, sentiment: Sentiment) =>
    request<Mention>(`/api/mentions/${mentionId}/sentiment`, { method: "POST", json: { sentiment } }),

  screening: (id: string) => get<Screening>(`/api/targets/${id}/screening`),
  matches: (status: MatchStatus = "pending") => get<ScreeningMatch[]>(`/api/screening/matches?status=${status}`),
  reviewMatch: (id: number, decision: MatchStatus, note: string) =>
    request<ScreeningMatch>(`/api/screening/matches/${id}/review`, { method: "POST", json: { decision, note } }),
  watchlists: () => get<Watchlist[]>("/api/watchlists"),
  // El archivo va tal cual (sin JSON): el servidor detecta UTF-8, Windows-1252 o UTF-16 y aguanta listas de cientos de MB.
  uploadWatchlist: (name: string, category: string, file: Blob) =>
    request<{ slug: string; entries: number; added: number; changed: number; removed: number }>(
      `/api/watchlists/custom/file?${new URLSearchParams({ name, category })}`,
      { method: "POST", body: file, headers: { "content-type": "application/octet-stream" } }),
  deleteWatchlist: (slug: string) => request<void>(`/api/watchlists/custom/${slug}`, { method: "DELETE" }),

  me: () => get<Me>("/api/auth/me"),
  login: (email: string, password: string) => request<Me>("/api/auth/login", { method: "POST", json: { email, password } }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/api/auth/password", { method: "POST", json: { currentPassword, newPassword } }),

  users: () => get<User[]>("/api/users"),
  createUser: (input: { email: string; name: string; role: Role; password: string }) =>
    request<User>("/api/users", { method: "POST", json: input }),
  updateUser: (id: string, changes: Partial<{ name: string; role: Role; active: boolean; password: string }>) =>
    request<User>(`/api/users/${id}`, { method: "PATCH", json: changes }),
  deleteUser: (id: string) => request<void>(`/api/users/${id}`, { method: "DELETE" }),

  audit: (filters: AuditFilters, before?: number, limit = 100) =>
    get<AuditPage>(`/api/audit?${auditQuery(filters, { before, limit })}`),
};

export const KIND_LABEL: Record<TargetKind, string> = {
  Person: "Persona",
  Company: "Empresa",
  Institution: "Institución",
  GovernmentArea: "Área de gobierno",
  Country: "País",
};
