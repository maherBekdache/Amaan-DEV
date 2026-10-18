// Hybrid check: decide everything we can on the phone, then send only the links
// to the paired computer for the sandbox + reputation sources.
import { analyzeQr, analyzeText, linksToCheck, markOffline, mergeServer, type Result } from "@amaan/core";
import { checkLinks, type Pairing } from "./server";

export interface Checked extends Result {
  serverNote: string | null; // why links weren't checked online, if they weren't
  warnings: string[];
}

export async function runCheck(input: { text?: string; qr?: string[] }, pairing: Pairing | null): Promise<Checked> {
  const local = input.qr ? analyzeQr(input.qr) : analyzeText(input.text ?? "");
  const links = linksToCheck(local);
  if (!links.length) return { ...local, serverNote: null, warnings: [] };
  if (!pairing) {
    return { ...markOffline(local), serverNote: "Links weren't checked online: this phone isn't connected to a computer.", warnings: [] };
  }
  try {
    const merged = mergeServer(local, await checkLinks(pairing, links));
    return { ...merged, serverNote: null, warnings: merged.warnings };
  } catch (e) {
    return { ...markOffline(local), serverNote: e instanceof Error ? e.message : String(e), warnings: [] };
  }
}
