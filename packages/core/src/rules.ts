// Amaan's local checks. Port of backend/amaan/scoring/local_rules.py.
import brandsData from "./data/brands.json";
import type { Payload } from "./payloads";
import { CRYPTO_SCHEMES } from "./payloads";
import { sig, type Signal } from "./types";
import { extractUrls, toUnicodeHost, type ExtractedUrl, type TextFlags } from "./urls";

interface Brand { name: string; domains: string[]; keywords: string[] }
const BRANDS: Brand[] = (brandsData as { brands: Brand[] }).brands;
const SHORTENERS = new Set<string>((brandsData as { shorteners: string[] }).shorteners);
const OFFICIALS = new Map<string, string>(BRANDS.flatMap((b) => b.domains.map((d) => [d, b.name] as [string, string])));
const FILE_LIKE_TLDS = new Set(["zip", "mov", "exe", "pdf", "doc", "apk", "scr"]);
const BAIT_WORDS = ["prize", "winner", "win", "gift", "bonus", "reward", "lottery", "lucky", "claim", "free",
  "verify", "verification", "secure", "login", "signin", "update", "wallet", "airdrop", "promo"];

const CONFUSABLES: Record<string, string> = {
  "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
  "ԁ": "d", "һ": "h", "ӏ": "l", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "ѕ": "s",
  "ԛ": "q", "ԝ": "w", "ɡ": "g", "ο": "o", "α": "a", "ν": "v", "ρ": "p", "τ": "t", "ι": "i",
  "κ": "k", "χ": "x", "ε": "e", "υ": "u", "0": "o", "1": "l", "3": "e", "5": "s", "@": "a",
};

export function skeleton(s: string): string {
  const base = s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
  return [...base].map((c) => CONFUSABLES[c] ?? c).join("").replaceAll("rn", "m").replaceAll("vv", "w");
}

const SCRIPTS: [string, RegExp][] = [
  ["latin", /[a-zÀ-ɏ]/i], ["cyrillic", /[Ѐ-ӿ]/], ["greek", /[Ͱ-Ͽ]/],
  ["arabic", /[؀-ۿ]/], ["hebrew", /[֐-׿]/], ["armenian", /[԰-֏]/],
];
const scriptsOf = (label: string) => new Set(SCRIPTS.filter(([, re]) => [...label].some((c) => re.test(c))).map(([n]) => n));

export function urlSignals(u: ExtractedUrl): Signal[] {
  const out: Signal[] = [];
  const reg = u.registrable.toLowerCase();
  const regUnicode = reg.includes("xn--") ? toUnicodeHost(reg) : reg;
  const official = OFFICIALS.get(reg);
  if (official) {
    out.push(sig("official_domain", `Official ${official} domain`,
      `${reg} is on Amaan's curated list of official domains. Still never share codes or passwords over chat.`, "good", "verified"));
  }
  if (u.hasUserinfo) {
    out.push(sig("userinfo_trick", "Link hides its real destination with '@'",
      "Everything before '@' in a link is ignored by the browser, so 'bank.com@evil.site' really opens evil.site.", "high"));
  }
  if (u.isIp) {
    out.push(sig("ip_host", "Link uses a raw IP address instead of a name",
      `Legitimate services almost always use a domain name; ${u.host} is a bare server address.`, "medium"));
  }
  if (u.hostAscii.includes("xn--")) {
    const mixed = u.host.split(".").some((l) => {
      const s = scriptsOf(l);
      const nonArabic = [...s].filter((x) => x !== "arabic").length;
      return nonArabic > 1 || (s.has("latin") && s.size > 1);
    });
    out.push(mixed
      ? sig("mixed_script", "Domain mixes alphabets (lookalike letters)",
        `'${u.host}' mixes letters from different alphabets, a classic trick to imitate a real site. Its real address is ${u.hostAscii}.`, "high")
      : sig("punycode_host", "International (non-Latin) domain",
        `Shown as '${u.host}', registered as ${u.hostAscii}. Check it is the site you expect.`, "low"));
  }
  if (!official && !u.isIp) {
    const sk = skeleton(regUnicode);
    const label = regUnicode.split(".")[0];
    let look = false;
    for (const [off, brand] of OFFICIALS) {
      const offLabel = off.split(".")[0];
      if (sk === skeleton(off) || (skeleton(label) === skeleton(offLabel) && label !== offLabel)) {
        out.push(sig("lookalike_domain", `Imitates ${brand}'s official domain`, `'${u.host}' looks like ${off} but is a different domain.`, "high"));
        look = true;
        break;
      }
    }
    if (!look) {
      const tokens = skeleton(u.host).split(/[.\-_0-9]+/).filter(Boolean);
      for (const b of BRANDS) {
        const hit = b.keywords.find((k) => tokens.includes(k) || (k.length >= 5 && tokens.some((t) => t.includes(k))));
        if (hit) {
          out.push(sig("brand_in_domain", `Uses the name '${b.name}' but is not a known official domain`,
            `${u.host} contains '${hit}', but ${b.name}'s official domain is ${b.domains.join(", ")}.`, "medium"));
          break;
        }
      }
    }
  }
  if (!official && !u.isIp && !SHORTENERS.has(reg)) {
    const name = u.suffix ? u.hostAscii.slice(0, -(u.suffix.length + 1)) : u.hostAscii;
    let found = BAIT_WORDS.filter((w) => name.toLowerCase().includes(w));
    found = found.filter((w) => !found.some((o) => o !== w && o.includes(w)));
    if (found.length) {
      out.push(sig("bait_domain", "Domain name uses bait words",
        `'${u.host}' contains ${found.map((w) => `'${w}'`).join(", ")}. Scam sites use names like this to look rewarding or official.`, "medium"));
    }
  }
  if (SHORTENERS.has(reg) || SHORTENERS.has(u.hostAscii)) {
    out.push(sig("shortener", "Shortened link hides the real destination",
      "Amaan never opens it. The server's sandbox follows it to find where it leads.", "low"));
  }
  const tld = u.suffix ? u.suffix.split(".").pop()! : "";
  if (FILE_LIKE_TLDS.has(tld)) {
    out.push(sig("file_like_tld", `Domain ending '.${tld}' looks like a file name`,
      `'${u.host}' is a website, not a .${tld} file, a trick used to make links look like attachments.`, "medium"));
  }
  if (u.scheme === "http") out.push(sig("no_https", "Not encrypted (http://)", "Anything typed on this page can be read by others on the network.", "low"));
  if (u.port !== null && u.port !== 80 && u.port !== 443) {
    out.push(sig("unusual_port", `Unusual port :${u.port}`, "Normal websites do not need a port number in the link.", "low"));
  }
  return out;
}

export function payloadSignals(p: Payload): Signal[] {
  const d = p.details;
  if (p.kind === "wifi") {
    if ((d.security ?? "").startsWith("open")) {
      return [sig("open_wifi", "Joins an open Wi-Fi network",
        `Network '${d.ssid}' has no password. Others on it may see your traffic; fake hotspots use this to steal logins.`, "medium")];
    }
    if (d.security === "WEP") return [sig("weak_wifi", "Joins a Wi-Fi network with broken (WEP) security", "", "medium")];
    return [sig("wifi", "Joins a Wi-Fi network", `Scanning connects your phone to '${d.ssid}'. Only join networks you trust.`, "info")];
  }
  if (p.kind === "tel") {
    const num = d.number ?? "";
    const intl = (num.startsWith("+") || num.startsWith("00")) && !/^(\+?961|00961)/.test(num);
    return [sig("tel", `Calls ${num}`, "Scanning starts a phone call. " +
      (intl ? "This is an international number; calls may be expensive." : "Check you know who this number belongs to."), intl ? "low" : "info")];
  }
  if (p.kind === "sms") {
    const body = Boolean(d.message);
    return [sig("sms", `Prepares an SMS to ${d.number ?? ""}`, body
      ? "A ready-made text message can sign you up for paid services or confirm a scam. Check the number and message before sending."
      : "Scanning opens a new SMS to this number.", body ? "medium" : "low")];
  }
  if (p.kind === "mailto") return [sig("mailto", `Writes an e-mail to ${d.address ?? ""}`, "", "info")];
  if (p.kind === "geo") return [sig("geo", "Opens a map location", d.location ?? "", "info")];
  if (p.scheme && CRYPTO_SCHEMES.has(p.scheme)) {
    return [sig("crypto_payment", `Crypto payment request (${p.scheme})`,
      "Crypto payments cannot be reversed. Scammers often use QR codes to collect them.", "high")];
  }
  return [];
}

export function textFlagSignals(f: TextFlags): Signal[] {
  const out: Signal[] = [];
  if (f.bidiOverride) out.push(sig("bidi_override", "Hidden text-direction characters",
    "The text contains invisible characters that reverse how letters are displayed, used to disguise links and file names.", "high"));
  if (f.zeroWidthInLink) out.push(sig("zero_width", "Invisible characters inside a link",
    "Zero-width characters were hidden inside a link, often to slip past filters.", "medium"));
  if (f.fullwidth) out.push(sig("fullwidth", "Unusual wide characters",
    "The text uses full-width letters or dots, sometimes used to disguise links.", "low"));
  if (f.defanged) out.push(sig("defanged", "Contains defanged links (e.g. hxxp, [.])",
    "Security teams write links this way to make them unclickable. We restored them for analysis.", "info"));
  return out;
}

export { extractUrls };
