import type { AIOpinion, Evidence, Health, ImportReport, Pairing, WaAlert, WaChat, WaPolicy, WaStatus } from "../types";

// Same origin only: the backend serves this app (CSP connect-src 'self').

export class ApiError extends Error {}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let detail = `Request failed (HTTP ${res.status})`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    /* not JSON */
  }
  throw new ApiError(detail);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "omit", ...init }).catch(() => {
    throw new ApiError("Amaan's backend is not running.");
  });
  return handle<T>(res);
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function analyzeText(input: { text: string; html?: string; uri_list?: string }): Promise<Evidence> {
  return call<Evidence>("/analyze/text", json("POST", input));
}

export function analyzeImage(file: Blob, source: "image" | "camera", name = "upload.png"): Promise<Evidence> {
  const form = new FormData();
  form.append("file", file, name);
  form.append("source", source);
  return call<Evidence>("/analyze/image", { method: "POST", body: form });
}

export const getHealth = (): Promise<Health | null> => call<Health>("/health").catch(() => null);

export const getPairing = (): Promise<Pairing> => call<Pairing>("/phone/pairing");

export function importChat(file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append("file", file, file.name);
  return call<ImportReport>("/import/chat", { method: "POST", body: form });
}

export const wa = {
  status: () => call<WaStatus>("/whatsapp/status"),
  link: () => call<WaStatus>("/whatsapp/link", { method: "POST" }),
  logout: () => call<WaStatus>("/whatsapp/logout", { method: "POST" }),
  chats: () => call<{ chats: WaChat[] } & WaPolicy>("/whatsapp/chats"),
  setPolicy: (policy: WaPolicy) => call<{ selected: number } & WaPolicy>("/whatsapp/selection", json("PUT", policy)),
  addNumber: (number: string) => call<{ id: string; selected: number }>("/whatsapp/chats", json("POST", { number })),
  alerts: () => call<WaAlert[]>("/whatsapp/alerts"),
  clearAlerts: () => call<{ cleared: boolean }>("/whatsapp/alerts", { method: "DELETE" }),
};

export function explain(evidence: Evidence, text?: string): Promise<AIOpinion> {
  return call<AIOpinion>("/ai/explain", json("POST", { evidence, text, open_page: true }));
}
