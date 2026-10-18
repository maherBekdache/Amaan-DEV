// What a QR code contains. Port of backend/amaan/extract/payloads.py.
import type { ItemKind } from "./types";

export const CRYPTO_SCHEMES = new Set(["bitcoin", "ethereum", "litecoin", "tron", "usdt", "bnb", "solana", "dogecoin", "monero"]);

export interface Payload {
  kind: ItemKind;
  raw: string;
  details: Record<string, string>;
  scheme: string | null;
}

function splitMecard(body: string): Record<string, string> {
  const fields: Record<string, string> = {};
  let key: string | null = null;
  let buf = "";
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === "\\" && i + 1 < body.length) {
      buf += body[++i];
      continue;
    }
    if (ch === ":" && key === null) {
      key = buf.toUpperCase();
      buf = "";
    } else if (ch === ";") {
      if (key !== null && !(key in fields)) fields[key] = buf;
      key = null;
      buf = "";
    } else buf += ch;
  }
  if (key !== null && !(key in fields)) fields[key] = buf;
  return fields;
}

const q = (query: string, name: string) => {
  for (const part of query.split("&")) {
    const [k, v = ""] = part.split("=");
    if (decodeURIComponent(k) === name) return decodeURIComponent(v.replace(/\+/g, " "));
  }
  return "";
};

export function classifyPayload(text: string): Payload {
  const raw = text.trim();
  const lower = raw.toLowerCase();
  if (lower.startsWith("wifi:")) {
    const f = splitMecard(raw.slice(5));
    const sec = (f.T || "nopass").toUpperCase();
    return { kind: "wifi", raw, scheme: "wifi", details: {
      ssid: f.S ?? "", security: sec === "NOPASS" || sec === "" ? "open (no password)" : sec,
      hidden: (f.H ?? "").toLowerCase() === "true" ? "yes" : "no", password: f.P ? "included (hidden)" : "none" } };
  }
  if (lower.startsWith("tel:")) return { kind: "tel", raw, scheme: "tel", details: { number: decodeURIComponent(raw.slice(4)).trim() } };
  if (/^(sms|smsto|mms|mmsto):/.test(lower)) {
    const i = raw.indexOf(":");
    const scheme = raw.slice(0, i).toLowerCase();
    const rest = raw.slice(i + 1);
    let number = rest;
    let body = "";
    if (rest.includes("?")) {
      number = rest.slice(0, rest.indexOf("?"));
      body = q(rest.slice(rest.indexOf("?") + 1), "body");
    } else if (rest.includes(":")) {
      number = rest.slice(0, rest.indexOf(":"));
      body = rest.slice(rest.indexOf(":") + 1);
    }
    const details: Record<string, string> = { number: decodeURIComponent(number).trim() };
    if (body) details.message = body.slice(0, 300);
    return { kind: "sms", raw, scheme, details };
  }
  if (lower.startsWith("mailto:")) {
    const [addr, query = ""] = raw.slice(7).split("?");
    const details: Record<string, string> = { address: decodeURIComponent(addr) };
    const subject = q(query, "subject");
    if (subject) details.subject = subject.slice(0, 200);
    return { kind: "mailto", raw, scheme: "mailto", details };
  }
  if (lower.startsWith("matmsg:")) {
    const f = splitMecard(raw.slice(7));
    return { kind: "mailto", raw, scheme: "matmsg", details: { address: f.TO ?? "", subject: (f.SUB ?? "").slice(0, 200) } };
  }
  if (lower.startsWith("geo:")) return { kind: "geo", raw, scheme: "geo", details: { location: raw.slice(4).split("?")[0] } };
  if (/^(https?|ftp):\/\//.test(lower) || lower.startsWith("www.")) {
    return { kind: "url", raw, scheme: lower.includes("://") ? lower.split(":")[0] : null, details: {} };
  }
  const sm = /^([a-z][a-z0-9+.\-]{1,20}):/.exec(lower);
  if (sm && CRYPTO_SCHEMES.has(sm[1])) {
    const address = raw.slice(raw.indexOf(":") + 1).split("?")[0];
    const details: Record<string, string> = { currency: sm[1], address };
    const amount = raw.includes("?") ? q(raw.slice(raw.indexOf("?") + 1), "amount") : "";
    if (amount) details.amount = amount;
    return { kind: "text", raw, scheme: sm[1], details };
  }
  if (lower.startsWith("mecard:") || lower.startsWith("begin:vcard")) {
    return { kind: "text", raw, scheme: lower.split(":")[0], details: { format: "contact card" } };
  }
  const other = sm && lower.includes("://") ? sm[1] : null;
  return { kind: "text", raw, scheme: other, details: other ? { scheme: other } : {} };
}
