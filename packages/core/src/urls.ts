// Find links in free text (English, Arabic, Arabizi). Port of backend/amaan/extract/urls.py.
// Nothing here touches the network; the public-suffix list is bundled with tldts.
import punycode from "punycode/punycode.js";
import { parse as parseDomain } from "tldts";

const ZERO_WIDTH = "​‌‍⁠﻿­᠎";
const BIDI_CONTROLS = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜";
const BIDI_OVERRIDES = /[‭‮]/;
const DOT_VARIANTS = /[。．｡․﹒]/g;
const TRAILING = new Set(".,;:!?'\"»«”“’‘…>]}،؛؟۔*_~".split(""));

const L = "0-9a-z\\u00c0-\\u024f\\u0370-\\u03ff\\u0400-\\u04ff";
const LABEL = `[${L}](?:[${L}\\-]{0,61}[${L}])?`;
const PATH = `(?:[/?#][^\\s<>"'\`]*)?`;
const SCHEME_RE = new RegExp(`(?<![a-z])(?:https?|ftp)://[^\\s<>"'\`]+`, "giu");
const WWW_RE = new RegExp(`(?<![${L}@.\\-/])www\\d{0,3}\\.[^\\s<>"'\`]+`, "giu");
const BARE_RE = new RegExp(`(?<![${L}@.\\-/:])(?:${LABEL}\\.)+${LABEL}(?::\\d{1,5})?${PATH}`, "giu");
const IP_RE = /(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5}(?:[/?#][^\s<>"'`]*)?|[/?#][^\s<>"'`]*)/gu;
const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/u;
const DEFANG: [RegExp, string][] = [
  [/\bhxxp(s?)\b/gi, "http$1"],
  [/\[\s*(?:\.|dot)\s*\]|\(\s*(?:\.|dot)\s*\)|\{\s*(?:\.|dot)\s*\}/gi, "."],
  [/\[\s*:\s*\]/g, ":"],
  [/\[\s*\/\s*\]/g, "/"],
];

export interface TextFlags {
  zeroWidthInLink: boolean;
  bidiOverride: boolean;
  defanged: boolean;
  fullwidth: boolean;
}

export interface ExtractedUrl {
  original: string;
  url: string; // host in punycode form; what goes to the server
  host: string; // Unicode
  hostAscii: string;
  scheme: string | null;
  registrable: string;
  suffix: string;
  isIp: boolean;
  hasUserinfo: boolean;
  port: number | null;
}

export function cleanText(text: string): { text: string; flags: TextFlags } {
  const flags: TextFlags = { zeroWidthInLink: false, bidiOverride: false, defanged: false, fullwidth: false };
  if (BIDI_OVERRIDES.test(text)) flags.bidiOverride = true;
  if (new RegExp(`[A-Za-z0-9./:][${ZERO_WIDTH}]+[A-Za-z0-9./]`, "u").test(text)) flags.zeroWidthInLink = true;
  let t = [...text].filter((c) => !ZERO_WIDTH.includes(c) && !BIDI_CONTROLS.includes(c)).join("");
  t = t.replace(DOT_VARIANTS, ".");
  if (/[！-～]/.test(t)) flags.fullwidth = true;
  t = t.normalize("NFKC");
  for (const [re, rep] of DEFANG) {
    const next = t.replace(re, rep);
    if (next !== t) flags.defanged = true;
    t = next;
  }
  return { text: t, flags };
}

function trimTrailing(c: string): string {
  while (c) {
    const last = c[c.length - 1];
    const opens = (c.match(/\(/g) ?? []).length;
    const closes = (c.match(/\)/g) ?? []).length;
    if (last === ")" && opens >= closes) break;
    if (TRAILING.has(last) || last === ")") {
      c = c.slice(0, -1);
      continue;
    }
    break;
  }
  return c;
}

const isIpv4 = (h: string) => /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.test(h) && h.split(".").every((n) => +n <= 255);

export function toAsciiHost(host: string): string | null {
  const h = host.replace(/^\.+|\.+$/g, "").toLowerCase();
  if (!h) return null;
  try {
    return punycode.toASCII(h);
  } catch {
    return null;
  }
}

export function toUnicodeHost(ascii: string): string {
  try {
    return punycode.toUnicode(ascii);
  } catch {
    return ascii;
  }
}

function rebuild(scheme: string | null, hostAscii: string, port: number | null, rest: string): string {
  return (scheme ? `${scheme.toLowerCase()}://` : "") + hostAscii + (port !== null ? `:${port}` : "") + rest;
}

export function parseCandidate(candidate: string, allowBareIp = true): ExtractedUrl | null {
  candidate = trimTrailing(candidate.trim());
  if (!candidate) return null;
  const schemeM = /^([a-z][a-z0-9+.\-]*):\/\//i.exec(candidate);
  const scheme = schemeM ? schemeM[1].toLowerCase() : null;
  const afterScheme = schemeM ? candidate.slice(schemeM[0].length) : candidate;
  const cut = afterScheme.search(/[/?#]/);
  const netloc = cut === -1 ? afterScheme : afterScheme.slice(0, cut);
  let rest = cut === -1 ? "" : afterScheme.slice(cut);
  const hasUserinfo = netloc.includes("@");
  const hostport = netloc.slice(netloc.lastIndexOf("@") + 1);
  let host = hostport;
  let port: number | null = null;
  const pm = /^(.*):(\d+)$/.exec(hostport);
  if (pm) {
    host = pm[1];
    port = Number(pm[2]);
  }
  // An Arabic word glued to the end of the host ("example.comهنا").
  const am = ARABIC.exec(host);
  if (am && /[a-z]/i.test(host.slice(0, am.index)) && host.slice(0, am.index).includes(".")) {
    host = host.slice(0, am.index);
    rest = "";
    port = null;
  }
  if (isIpv4(host)) {
    if (!allowBareIp && !scheme && port === null && !rest) return null;
    return { original: candidate, url: rebuild(scheme, host, port, rest), host, hostAscii: host, scheme,
             registrable: host, suffix: "", isIp: true, hasUserinfo, port };
  }
  const hostAscii = toAsciiHost(host);
  if (!hostAscii || !hostAscii.includes(".")) return null;
  const d = parseDomain(hostAscii, { allowPrivateDomains: false });
  if (!d.domain || !d.publicSuffix || d.isIcann !== true) return null;
  const tld = d.publicSuffix.split(".").pop() ?? "";
  if (!(/^[a-z]+$/.test(tld) || tld.startsWith("xn--"))) return null;
  return { original: candidate, url: rebuild(scheme, hostAscii, port, rest), host: toUnicodeHost(hostAscii), hostAscii,
           scheme, registrable: d.domain, suffix: d.publicSuffix, isIp: false, hasUserinfo, port };
}

const keyOf = (url: string) => url.toLowerCase().replace(/\/+$/, "").replace(/^[a-z]+:\/\//, "");

export function extractUrls(text: string, limit = 50): { urls: ExtractedUrl[]; flags: TextFlags; cleaned: string; truncated: boolean } {
  const { text: cleaned, flags } = cleanText(text);
  const found: [number, ExtractedUrl][] = [];
  const taken: [number, number][] = [];
  const overlaps = (s: number, e: number) => taken.some(([a, b]) => s < b && a < e);
  for (const re of [SCHEME_RE, WWW_RE, IP_RE, BARE_RE]) {
    re.lastIndex = 0;
    for (const m of cleaned.matchAll(re)) {
      const start = m.index ?? 0;
      const end = start + m[0].length;
      if (overlaps(start, end)) continue;
      if (re === BARE_RE && cleaned[end] === "@") continue; // name.surname@ of an email
      const parsed = parseCandidate(m[0], re !== BARE_RE);
      if (!parsed) continue;
      taken.push([start, start + parsed.original.length]);
      found.push([start, parsed]);
    }
  }
  found.sort((a, b) => a[0] - b[0]);
  const seen = new Set<string>();
  const unique: ExtractedUrl[] = [];
  for (const [, u] of found) {
    const k = keyOf(u.url);
    if (seen.has(k)) continue;
    seen.add(k);
    unique.push(u);
  }
  return { urls: unique.slice(0, limit), flags, cleaned, truncated: unique.length > limit };
}

/** Safe to show: not clickable, not auto-linked. */
export function defang(value: string): string {
  let v = value.replace(/^http/i, "hxxp").replace(/^ftp/i, "fxp");
  const i = v.indexOf("://");
  const head = i >= 0 ? v.slice(0, i + 3) : "";
  const target = i >= 0 ? v.slice(i + 3) : v;
  const cut = target.search(/[/?#]/);
  const hostPart = cut === -1 ? target : target.slice(0, cut);
  const rest = cut === -1 ? "" : target.slice(cut);
  v = head + hostPart.replaceAll(".", "[.]") + rest;
  return v;
}
