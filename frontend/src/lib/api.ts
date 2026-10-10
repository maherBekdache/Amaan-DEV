import type { Evidence, Health } from "../types";

// Same-origin by default. An Electron build can point this at the local backend.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

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

export async function analyzeText(input: { text: string; html?: string; uri_list?: string }): Promise<Evidence> {
  const res = await fetch(`${BASE}/analyze/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    credentials: "omit",
  }).catch(() => {
    throw new ApiError("Amaan's backend is not running.");
  });
  return handle<Evidence>(res);
}

export async function analyzeImage(file: Blob, source: "image" | "camera", name = "upload.png"): Promise<Evidence> {
  const form = new FormData();
  form.append("file", file, name);
  form.append("source", source);
  const res = await fetch(`${BASE}/analyze/image`, { method: "POST", body: form, credentials: "omit" }).catch(() => {
    throw new ApiError("Amaan's backend is not running.");
  });
  return handle<Evidence>(res);
}

export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${BASE}/health`, { credentials: "omit" });
    return res.ok ? ((await res.json()) as Health) : null;
  } catch {
    return null;
  }
}
