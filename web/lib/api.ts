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
}

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
  sentiment: "positive" | "negative" | "neutral";
  score: number;
  severe: boolean;
  topic: string | null;
  summary: string | null;
  interactions: number;
}

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
  entityType: "user" | "target" | null;
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
    const message = typeof detail === "string" ? detail : detail?.message ?? `Error ${res.status}`;
    throw new ApiError(res.status, message, body);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const get = <T,>(path: string) => request<T>(path);

export const api = {
  targets: () => get<Target[]>("/api/targets"),
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
  createTarget: (input: Omit<Target, "id" | "enabled">) => request<Target>("/api/targets", { method: "POST", json: input }),

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
