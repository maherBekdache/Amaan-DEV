// "Check a WhatsApp chat" on the phone: the exported chat is read and analyzed here.
// Only the links found (at most 15, most suspicious first) go to the paired computer.
// The picked file and any photo written for QR scanning are deleted right after use.
import {
  analyzeQr, defang, extractUrls, linksToCheck, loadExport, markOffline, mergeServer, planChat, worst,
  type ChatExport, type ChatMessage, type Result, type RiskLevel, type ServerEvidence,
} from "@amaan/core";
import { scanFromURLAsync } from "expo-camera";
import * as DocumentPicker from "expo-document-picker";
import { File, Paths } from "expo-file-system";
import { Platform } from "react-native";
import type { Checked } from "./check";
import { checkLinksBatched, type Pairing } from "./server";

const MAX_FILE_BYTES = 60 * 1024 * 1024;
const LINK_BUDGET = 15;
const SNIPPET = 400;
const ORDER: Record<RiskLevel, number> = { High: 0, Medium: 1, Low: 2 };

export interface ChatFinding { key: string; date: string; time: string; sender: string; text: string; attachment?: string; result: Checked }
export interface ChatReport {
  title: string;
  riskLevel: RiskLevel;
  messagesTotal: number;
  messagesChecked: number;
  linksFound: number;
  linksChecked: number;
  imagesChecked: number;
  findings: ChatFinding[];
  notes: string[];
}

/** Show a message without live links: every link in it is defanged. */
export function defangText(text: string): string {
  let out = text;
  for (const u of extractUrls(text, 50).urls) out = out.split(u.original).join(defang(u.url));
  return out;
}

/** Let the user pick the exported chat (.txt or .zip) and read it into memory. */
export async function pickChat(): Promise<ChatExport | null> {
  const pick = await DocumentPicker.getDocumentAsync({ type: "*/*", copyToCacheDirectory: true, multiple: false });
  const asset = pick.canceled ? null : pick.assets?.[0];
  if (!asset) return null;
  if ((asset.size ?? 0) > MAX_FILE_BYTES) throw new Error("This file is too large (max 60 MB). Export the chat without media.");
  let bytes: Uint8Array;
  if (Platform.OS === "web") {
    bytes = new Uint8Array(await asset.file!.arrayBuffer());
  } else {
    const file = new File(asset.uri);
    try {
      bytes = await file.bytes();
    } finally {
      try { file.delete(); } catch { /* the system cleans its cache too */ }
    }
  }
  return loadExport(asset.name, bytes);
}

async function scanImage(name: string, bytes: Uint8Array): Promise<string[]> {
  if (Platform.OS === "web") {
    const url = URL.createObjectURL(new Blob([bytes as BlobPart]));
    try { return (await scanFromURLAsync(url, ["qr"])).map((c) => c.data); } finally { URL.revokeObjectURL(url); }
  }
  const ext = name.toLowerCase().match(/\.(jpe?g|png|webp)$/)?.[0] ?? ".jpg";
  const tmp = new File(Paths.cache, `amaan-scan-${Date.now()}${ext}`);
  try {
    tmp.write(bytes);
    return (await scanFromURLAsync(tmp.uri, ["qr"])).map((c) => c.data);
  } finally {
    try { tmp.delete(); } catch { /* not created */ }
  }
}

export async function analyzeChat(ex: ChatExport, pairing: Pairing | null, progress: (s: string) => void): Promise<ChatReport> {
  progress(`Reading ${ex.messages.length} messages…`);
  const plan = planChat(ex.messages, LINK_BUDGET);

  // QR codes in the chat's photos (only when exported "with media").
  const byAttachment = new Map<string, ChatMessage>();
  for (const m of ex.messages) for (const a of m.attachments) byAttachment.set(a.trim().toLowerCase(), m);
  const photos: { name: string; message?: ChatMessage; result: Result }[] = [];
  let imagesChecked = 0;
  for (const [name, bytes] of ex.images) {
    progress(`Looking for QR codes in photos (${imagesChecked + 1}/${ex.images.size})…`);
    try {
      const codes = (await scanImage(name, bytes)).filter(Boolean);
      imagesChecked += 1;
      if (codes.length) photos.push({ name, message: byAttachment.get(name.toLowerCase()), result: analyzeQr(codes) });
    } catch { /* unreadable image: skip */ }
  }
  const links = [...plan.links];
  for (const p of photos) for (const l of linksToCheck(p.result)) if (!links.includes(l) && links.length < LINK_BUDGET) links.push(l);
  const linksFound = plan.linksFound + photos.reduce((n, p) => n + linksToCheck(p.result).length, 0);

  let server: ServerEvidence | null = null;
  let serverNote: string | null = null;
  if (links.length && pairing) {
    progress(`Checking ${links.length} links on your computer (up to a minute)…`);
    try { server = await checkLinksBatched(pairing, links); } catch (e) { serverNote = e instanceof Error ? e.message : String(e); }
  } else if (links.length) {
    serverNote = "Links weren't checked online: this phone isn't connected to a computer.";
  }
  const finish = (r: Result): Checked => server
    ? { ...mergeServer(r, server), serverNote: null }
    : { ...markOffline(r), serverNote, warnings: [] };

  const findings: ChatFinding[] = [];
  for (const { message: m, result } of plan.candidates) {
    const r = finish(result);
    if (r.riskLevel !== "Low") findings.push({ key: `m${m.index}`, date: m.date, time: m.time, sender: m.sender, text: m.text.slice(0, SNIPPET), result: r });
  }
  for (const p of photos) {
    findings.push({ key: `p${p.name}`, date: p.message?.date ?? "", time: p.message?.time ?? "", sender: p.message?.sender ?? "",
                    text: `QR code in ${p.name}`, attachment: p.name, result: finish(p.result) });
  }
  findings.sort((a, b) => ORDER[a.result.riskLevel] - ORDER[b.result.riskLevel] || a.key.localeCompare(b.key, undefined, { numeric: true }));

  const notes: string[] = [];
  if (serverNote) notes.push(serverNote);
  if (server) notes.push(...server.warnings);
  if (linksFound > links.length) notes.push(`${linksFound} links found; the ${links.length} most suspicious were checked online, the rest with Amaan's own rules.`);
  if (ex.skippedImages) notes.push(`${ex.skippedImages} more photos were not scanned (limit ${ex.images.size}).`);
  return {
    title: ex.title, riskLevel: worst(...findings.map((f) => f.result.riskLevel)), messagesTotal: ex.messages.length,
    messagesChecked: plan.candidates.length, linksFound, linksChecked: server ? links.length : 0, imagesChecked, findings, notes,
  };
}
