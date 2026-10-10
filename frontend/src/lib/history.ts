import type { Evidence, InputType, RiskLevel } from "../types";

/**
 * Local history, kept only in this browser (localStorage).
 * Privacy: we store the time, input type, verdict and defanged host names.
 * No message text, no full links, no images.
 */

export interface HistoryEntry {
  id: string;
  at: string;
  inputType: InputType;
  risk: RiskLevel;
  hosts: string[];
  itemCount: number;
}

const KEY = "amaan.history.v1";
const MAX = 50;

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function save(entries: HistoryEntry[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX)));
  } catch {
    /* storage blocked or full: history is a convenience only */
  }
}

export function addToHistory(ev: Evidence): HistoryEntry[] {
  const hosts = Array.from(
    new Set(
      ev.items.map((i) => (i.host_ascii ? i.host_ascii.replaceAll(".", "[.]") : kindLabel(i.kind))).filter(Boolean),
    ),
  ).slice(0, 5);
  const entry: HistoryEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    at: ev.analyzed_at,
    inputType: ev.input_type,
    risk: ev.risk_level,
    hosts,
    itemCount: ev.items.length,
  };
  const next = [entry, ...loadHistory()];
  save(next);
  return next.slice(0, MAX);
}

export function clearHistory(): HistoryEntry[] {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  return [];
}

function kindLabel(kind: string): string {
  return { wifi: "Wi-Fi", tel: "phone", sms: "SMS", mailto: "e-mail", geo: "location", text: "text" }[kind] ?? kind;
}
