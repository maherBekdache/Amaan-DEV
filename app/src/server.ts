// The laptop / server the phone is paired with (hybrid mode).
// Only links go there; messages and images never leave the phone.
import AsyncStorage from "@react-native-async-storage/async-storage";
import type { RiskLevel, ServerEvidence, ServerItem, Signal } from "@amaan/core";

export interface Pairing { server: string; token: string }

const KEY = "amaan.pairing";
const CHECK_TIMEOUT_MS = 90_000; // the sandbox + sources can take ~1 min
const PRIVATE_HOST = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$|[a-z0-9-]+\.local$)/i;

/** Read an `amaan://pair?server=...&token=...` code. Returns null if it isn't one. */
export function parsePairing(data: string): Pairing | null {
  const m = /^amaan:\/\/pair\?(.*)$/i.exec(data.trim());
  if (!m) return null;
  const q = new URLSearchParams(m[1]);
  const server = (q.get("server") ?? "").replace(/\/+$/, "");
  const token = q.get("token") ?? "";
  if (!/^https?:\/\/[^\s/?#]+$/i.test(server) || token.length < 16) return null;
  return { server, token };
}

export const hostOf = (server: string) => server.replace(/^https?:\/\//i, "");
export const isLocalNetwork = (server: string) => PRIVATE_HOST.test(hostOf(server));

export async function loadPairing(): Promise<Pairing | null> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Pairing) : null;
  } catch {
    return null;
  }
}

export const savePairing = (p: Pairing) => AsyncStorage.setItem(KEY, JSON.stringify(p));
export const forgetPairing = () => AsyncStorage.removeItem(KEY);

async function call(p: Pairing, path: string, init: RequestInit = {}, timeoutMs = 8000): Promise<Response> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(`${p.server}${path}`, {
      ...init,
      signal: ctl.signal,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${p.token}`, "Content-Type": "application/json" },
    });
    if (res.status === 401 || res.status === 403) throw new Error("The computer refused the phone. Scan the pairing code again.");
    if (!res.ok) throw new Error(`The computer answered with an error (${res.status}).`);
    return res;
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") throw new Error("The computer took too long to answer.");
    if (e instanceof TypeError) throw new Error("Can't reach the computer. Same Wi-Fi? Is Amaan running there?");
    throw e;
  } finally {
    clearTimeout(t);
  }
}

export async function health(p: Pairing): Promise<{ link_sandbox: boolean }> {
  return (await call(p, "/gateway/health")).json();
}

/** Ask the server to check links (sandbox + reputation sources). */
export async function checkLinks(p: Pairing, urls: string[]): Promise<ServerEvidence> {
  const res = await call(p, "/gateway/analyze/link", { method: "POST", body: JSON.stringify({ urls: urls.slice(0, 10) }) }, CHECK_TIMEOUT_MS);
  return res.json();
}

/** Check up to `budget` links, 10 per request (the server's limit). */
export async function checkLinksBatched(p: Pairing, urls: string[]): Promise<ServerEvidence> {
  const out: ServerEvidence = { items: [], warnings: [], complete: true };
  for (let i = 0; i < urls.length; i += 10) {
    const r = await checkLinks(p, urls.slice(i, i + 10));
    out.items.push(...r.items);
    out.warnings.push(...r.warnings.filter((w) => !out.warnings.includes(w)));
    out.complete &&= r.complete;
  }
  return out;
}

// Live WhatsApp watching runs on the computer (whatsapp-bridge); the phone only shows its alerts.
export interface WaAlert {
  id: number;
  received_at: string;
  chat_name: string;
  sender: string;
  kind: string;
  text: string;
  evidence: { risk_level: RiskLevel; signals: Signal[]; items: ServerItem[] };
}
export interface WaLive {
  status: { enabled: boolean; state?: string; selected?: number; mode?: string; error?: string | null; checked_total?: number };
  alerts: WaAlert[];
}

export async function whatsappLive(p: Pairing): Promise<WaLive> {
  return (await call(p, "/gateway/whatsapp")).json();
}
