// Hybrid check: decide everything we can on the phone, then send only the links
// to the paired computer for the sandbox + reputation sources.
import { analyzeQr, analyzeText, linksToCheck, markOffline, mergeServer, type Result, type ServerItem } from "@amaan/core";
import { checkLinks, type Pairing } from "./server";

export interface Checked extends Result {
  serverNote: string | null; // why links weren't checked online, if they weren't
  warnings: string[];
  server?: ServerItem[]; // the computer's link checks (sandbox + sources), when it answered
  inputType?: "text" | "image";
}

export async function runCheck(input: { text?: string; qr?: string[] }, pairing: Pairing | null): Promise<Checked> {
  const inputType = input.qr ? "image" : "text";
  const local = input.qr ? analyzeQr(input.qr) : analyzeText(input.text ?? "");
  const links = linksToCheck(local);
  if (!links.length) return { ...local, serverNote: null, warnings: [], inputType };
  if (!pairing) {
    return { ...markOffline(local), serverNote: "Links weren't checked online: this phone isn't connected to a computer.", warnings: [], inputType };
  }
  try {
    return { ...mergeServer(local, await checkLinks(pairing, links)), serverNote: null, inputType };
  } catch (e) {
    return { ...markOffline(local), serverNote: e instanceof Error ? e.message : String(e), warnings: [], inputType };
  }
}
