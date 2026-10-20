// WhatsApp "Export chat" files (.txt, or .zip with photos), read on the device.
// Port of backend/amaan/importers/whatsapp_export.py + the import report in
// backend/amaan/api/whatsapp.py. Nothing here touches the network.
import { strFromU8, unzipSync } from "fflate";
import { analyzeText, linksToCheck } from "./analyze";
import { textCueSignals } from "./cues";
import { urlSignals } from "./rules";
import type { Result } from "./types";
import { extractUrls } from "./urls";

export const MAX_TEXT_BYTES = 20 * 1024 * 1024;
export const MAX_IMAGES = 15;
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_UNZIPPED = 80 * 1024 * 1024; // zip-bomb guard
const IMAGE_EXT = /\.(jpe?g|png|webp)$/i;

const DATE = String.raw`\d{1,4}[./-]\d{1,2}[./-]\d{1,4}`;
const TIME = String.raw`\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[APap]\.?\s?[Mm]\.?)?`;
const IOS = new RegExp(String.raw`^\[(${DATE}),?\s(${TIME})\]\s(.+?):\s(.*)$`);
const ANDROID = new RegExp(String.raw`^(${DATE}),?\s(${TIME})\s[-–]\s(.+?):\s(.*)$`);
const SYSTEM = new RegExp(String.raw`^\[?(${DATE}),?\s(${TIME})\]?\s[-–]?\s?[^:]+$`); // "… - Messages are end-to-end encrypted"
const ATTACHED = /<attached:\s*([^>]+)>|(\S+\.(?:jpe?g|png|webp))\s*\(file attached\)/gi;
const INVISIBLE = /[‎‏‪‫‬]/g;

export class ExportRejected extends Error {}

export interface ChatMessage { index: number; date: string; time: string; sender: string; text: string; attachments: string[] }
export interface ChatExport { title: string; messages: ChatMessage[]; images: Map<string, Uint8Array>; skippedImages: number }

const clean = (line: string) => line.replace(INVISIBLE, "").replace(/[  ]/g, " ").replace(/\r$/, "");

export function parseChat(text: string): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = clean(raw);
    const m = IOS.exec(line) ?? ANDROID.exec(line);
    if (m) messages.push({ index: messages.length, date: m[1], time: m[2], sender: m[3].trim(), text: m[4], attachments: [] });
    else if (SYSTEM.test(line)) continue; // encryption notices, "X added Y", etc.
    else if (messages.length && line.trim()) messages[messages.length - 1].text += "\n" + line;
  }
  for (const msg of messages) msg.attachments = [...msg.text.matchAll(ATTACHED)].map((a) => a[1] ?? a[2]);
  return messages;
}

function decode(data: Uint8Array): string {
  if (data[0] === 0xff && data[1] === 0xfe) {
    let s = "";
    for (let i = 2; i + 1 < data.length; i += 2) s += String.fromCharCode(data[i] | (data[i + 1] << 8));
    return s;
  }
  const s = strFromU8(data);
  return s.charCodeAt(0) === 0xfeff ? s.slice(1) : s;
}

export function title(filename: string): string {
  const base = filename.replace(/\.(txt|zip)$/i, "").replace(/^WhatsApp Chat (with|-)\s*/i, "").replace(/^[\s\-_]+|[\s\-_]+$/g, "");
  return base && !["_chat", "chat"].includes(base.toLowerCase()) ? base : "WhatsApp chat";
}

const baseName = (p: string) => p.split("/").pop() ?? p;

export function loadExport(filename: string, data: Uint8Array): ChatExport {
  const name = baseName(filename || "chat.txt");
  if (data[0] === 0x50 && data[1] === 0x4b) return loadZip(data);
  if (data.length > MAX_TEXT_BYTES) throw new ExportRejected("The chat file is too large.");
  const messages = parseChat(decode(data));
  if (!messages.length) throw new ExportRejected("This doesn't look like a WhatsApp chat export (no messages found).");
  return { title: title(name), messages, images: new Map(), skippedImages: 0 };
}

function loadZip(data: Uint8Array): ChatExport {
  // First pass: sizes only (nothing is unpacked), to refuse zip bombs.
  let total = 0;
  const sizes = new Map<string, number>();
  try {
    unzipSync(data, { filter: (f) => { total += f.originalSize; sizes.set(f.name, f.originalSize); return false; } });
  } catch {
    throw new ExportRejected("The .zip file is damaged.");
  }
  if (total > MAX_TOTAL_UNZIPPED) throw new ExportRejected("The .zip file is too large once unpacked.");
  const texts = [...sizes].filter(([n, s]) => n.toLowerCase().endsWith(".txt") && s <= MAX_TEXT_BYTES);
  if (!texts.length) throw new ExportRejected("No chat text (.txt) found inside the .zip file.");
  const chatName = (texts.find(([n]) => n.toLowerCase().includes("chat")) ?? texts.reduce((a, b) => (b[1] > a[1] ? b : a)))[0];
  const messages = parseChat(decode(unzipSync(data, { filter: (f) => f.name === chatName })[chatName]));
  if (!messages.length) throw new ExportRejected("This doesn't look like a WhatsApp chat export (no messages found).");

  const referenced = new Set(messages.flatMap((m) => m.attachments.map((a) => a.trim().toLowerCase())));
  const candidates = [...sizes].filter(([n, s]) => IMAGE_EXT.test(n) && s <= MAX_IMAGE_BYTES).map(([n]) => n)
    .sort((a, b) => Number(!referenced.has(baseName(a).toLowerCase())) - Number(!referenced.has(baseName(b).toLowerCase())));
  const keep = new Set(candidates.slice(0, MAX_IMAGES));
  const files = keep.size ? unzipSync(data, { filter: (f) => keep.has(f.name) }) : {};
  const images = new Map(Object.entries(files).map(([n, b]) => [baseName(n), b]));
  return { title: title(baseName(chatName)), messages, images, skippedImages: Math.max(0, candidates.length - MAX_IMAGES) };
}

/** How suspicious a message looks before any network check (for ordering). */
function localPriority(text: string): number {
  const sev: Record<string, number> = { high: 3, medium: 2, low: 1 };
  let best = 0;
  for (const u of extractUrls(text, 10).urls) for (const s of urlSignals(u)) best = Math.max(best, sev[s.severity] ?? 0);
  return best + (textCueSignals(extractUrls(text, 1).cleaned, false).length ? 1 : 0);
}

export interface ChatCandidate { message: ChatMessage; result: Result }
export interface ChatPlan { candidates: ChatCandidate[]; links: string[]; linksFound: number }

/** Analyze every message that has a link or a scam phrase; pick the links worth checking online, most suspicious first. */
export function planChat(messages: ChatMessage[], linkBudget = 15): ChatPlan {
  const candidates = messages
    .filter((m) => extractUrls(m.text, 1).urls.length || textCueSignals(extractUrls(m.text, 1).cleaned, false).length)
    .slice(0, 5000)
    .map((message) => ({ message, result: analyzeText(message.text) }));
  const ordered = [...candidates].sort((a, b) => localPriority(b.message.text) - localPriority(a.message.text) || b.message.index - a.message.index);
  const links = [...new Set(ordered.flatMap((c) => linksToCheck(c.result)))];
  return { candidates, links: links.slice(0, linkBudget), linksFound: links.length };
}
