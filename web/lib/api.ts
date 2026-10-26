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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  targets: () => get<Target[]>("/api/targets"),
  risk: (id: string, hours = 24 * 7) => get<Risk[]>(`/api/targets/${id}/risk?hours=${hours}`),
  mentions: (id: string, limit = 40) => get<Mention[]>(`/api/targets/${id}/mentions?limit=${limit}`),
  breakdown: (id: string, hours = 24) => get<Breakdown>(`/api/targets/${id}/breakdown?hours=${hours}`),
  alerts: (id: string) => get<Alert[]>(`/api/targets/${id}/alerts`),
  createTarget: async (input: Omit<Target, "id" | "enabled">) => {
    const res = await fetch(`${API_URL}/api/targets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) throw new Error(`No se pudo crear (${res.status})`);
    return (await res.json()) as Target;
  },
};

export const KIND_LABEL: Record<TargetKind, string> = {
  Person: "Persona",
  Company: "Empresa",
  Institution: "Institución",
  GovernmentArea: "Área de gobierno",
  Country: "País",
};
