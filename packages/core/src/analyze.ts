// On-device analysis + merging the server's link check (hybrid mode).
import { textCueSignals } from "./cues";
import { classifyPayload } from "./payloads";
import { payloadSignals, textFlagSignals, urlSignals } from "./rules";
import type { Item, Result, RiskLevel, Severity, Signal } from "./types";
import { sig } from "./types";
import { defang, extractUrls, parseCandidate, type ExtractedUrl } from "./urls";

const ORDER: Record<RiskLevel, number> = { Low: 0, Medium: 1, High: 2 };
const SEV: Partial<Record<Severity, RiskLevel>> = { high: "High", medium: "Medium" };
export const worst = (...ls: RiskLevel[]): RiskLevel => ls.reduce((a, b) => (ORDER[b] > ORDER[a] ? b : a), "Low" as RiskLevel);

function itemLevel(kind: Item["kind"], signals: Signal[], checked: boolean): RiskLevel {
  let level = worst(...signals.map((s) => SEV[s.severity]).filter(Boolean) as RiskLevel[]);
  // A link nobody could check is never shown as safe, unless it is a verified official domain.
  if (kind === "url" && !checked && !signals.some((s) => s.label === "verified")) level = worst(level, "Medium");
  return level;
}

function linkItem(u: ExtractedUrl, source: Item["source"]): Item {
  const signals = urlSignals(u);
  return { kind: "url", source, display: defang(u.url), url: u.url, host: u.host, hostAscii: u.hostAscii, details: {},
           signals, riskLevel: itemLevel("url", signals, false), checked: false };
}

export function overallLevel(items: Item[], messageSignals: Signal[]): RiskLevel {
  let level = worst(...items.map((i) => i.riskLevel), ...(messageSignals.map((s) => SEV[s.severity]).filter(Boolean) as RiskLevel[]));
  const cues = messageSignals.filter((s) => s.id.startsWith("cue_"));
  const flaggedLink = items.some((i) => i.kind === "url" && i.signals.some((s) => s.severity === "medium" || s.severity === "high"));
  if (cues.length >= 2 && flaggedLink) level = "High";
  return level;
}

/** Everything that can be decided on the device, from a message. */
export function analyzeText(text: string): Result {
  const ex = extractUrls(text, 20);
  const items = ex.urls.map((u) => linkItem(u, "text"));
  const signals = [...textFlagSignals(ex.flags), ...textCueSignals(ex.cleaned, items.length > 0)];
  return { items, signals, riskLevel: overallLevel(items, signals), complete: items.length === 0 };
}

/** Everything that can be decided on the device, from decoded QR codes. */
export function analyzeQr(payloads: string[]): Result {
  const items: Item[] = [];
  const seen = new Set<string>();
  for (const raw of payloads) {
    const p = classifyPayload(raw);
    if (p.kind === "url") {
      const u = parseCandidate(p.raw);
      if (u && !seen.has(u.url)) {
        seen.add(u.url);
        items.push(linkItem(u, "qr"));
      } else if (!u) {
        items.push({ kind: "text", source: "qr", display: p.raw.slice(0, 200), details: { note: "Looks like a link but is not a valid address" },
                     signals: [], riskLevel: "Low", checked: true });
      }
      continue;
    }
    const embedded = p.kind === "text" ? extractUrls(p.raw, 10).urls : [];
    for (const u of embedded) if (!seen.has(u.url)) {
      seen.add(u.url);
      items.push(linkItem(u, "qr"));
    }
    if (embedded.length && !Object.keys(p.details).length) continue;
    const signals = payloadSignals(p);
    const display = p.kind === "wifi" ? `Wi-Fi network “${p.details.ssid ?? ""}”` : p.kind === "text" ? defang(p.raw.slice(0, 200)) : p.raw.slice(0, 200);
    items.push({ kind: p.kind, source: "qr", display, details: p.details, signals, riskLevel: itemLevel(p.kind, signals, true), checked: true });
  }
  return { items, signals: [], riskLevel: overallLevel(items, []), complete: items.every((i) => i.checked) };
}

/** Links the device found; only these are sent to the server (hybrid mode). */
export const linksToCheck = (r: Result): string[] => r.items.filter((i) => i.kind === "url" && !i.checked && i.url).map((i) => i.url!);

// Shape of the server's answer (backend Evidence), only what we use.
export interface ServerItem { display: string; host_ascii: string | null; signals: Signal[]; risk_level: RiskLevel; sources?: unknown[]; urlvet?: unknown }
export interface ServerEvidence { items: ServerItem[]; warnings: string[]; complete: boolean }

/** Replace the device's link items with the server's fuller result for the same links. */
export function mergeServer(r: Result, server: ServerEvidence): Result & { server: ServerItem[]; warnings: string[] } {
  const byHost = new Map(server.items.filter((s) => s.host_ascii).map((s) => [s.host_ascii!, s]));
  const items = r.items.map((i) => {
    const s = i.kind === "url" && i.hostAscii ? byHost.get(i.hostAscii) : undefined;
    return s ? { ...i, signals: s.signals, riskLevel: s.risk_level, checked: true } : i;
  });
  return { items, signals: r.signals, riskLevel: overallLevel(items, r.signals), complete: server.complete && items.every((i) => i.checked),
           server: server.items, warnings: server.warnings };
}

/** When the server can't be reached: say so, in the result itself. */
export function markOffline(r: Result): Result {
  const items = r.items.map((i) => i.kind === "url" && !i.checked
    ? { ...i, signals: [...i.signals, sig("link_not_checked", "Link couldn't be checked online", "No connection to the Amaan server. Until it is checked, treat it as unknown: don't log in or pay there.", "low")] }
    : i);
  return { ...r, items, riskLevel: overallLevel(items, r.signals) };
}

export const ADVICE: Record<RiskLevel, { title: string; advice: string }> = {
  High: { title: "Dangerous", advice: "Don't open it, don't scan it, and never share codes, passwords or card details." },
  Medium: { title: "Be careful", advice: "Check with the sender another way (call them) before you open anything or pay." },
  Low: { title: "No warning signs found", advice: "Looks OK, but stay alert: never share verification codes with anyone." },
};

/** The most important reasons, for the "Why?" list. */
export function topReasons(r: Result, n = 5): Signal[] {
  const rank: Severity[] = ["high", "medium", "low", "good", "info"];
  const all = [...r.signals, ...r.items.flatMap((i) => i.signals)].filter((s) => s.severity !== "info");
  const seen = new Set<string>();
  return all.sort((a, b) => rank.indexOf(a.severity) - rank.indexOf(b.severity))
    .filter((s) => (seen.has(s.title) ? false : (seen.add(s.title), true))).slice(0, n);
}
