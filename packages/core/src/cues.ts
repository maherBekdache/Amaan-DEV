// Scam-script cues (English, Arabic, Arabizi). Port of backend/amaan/scoring/text_cues.py;
// the patterns themselves are shared in data/cues.json.
import cuesData from "./data/cues.json";
import { sig, type Signal } from "./types";
import { extractUrls } from "./urls";

interface CueDef { id: string; title: string; why: string; weight: number; patterns: string[] }
const DATA = cuesData as { combo_threshold: number; cues: CueDef[] };

export function normalizeArabic(text: string): string {
  let t = text.replace(/[ً-ٰٟـ]/g, "");
  for (const [a, b] of [["أ", "ا"], ["إ", "ا"], ["آ", "ا"], ["ئ", "ء"], ["ؤ", "ء"], ["ة", "ه"], ["ى", "ي"]]) t = t.replaceAll(a, b);
  return t;
}

const COMPILED = DATA.cues.map((c) => ({ ...c, res: c.patterns.map((p) => new RegExp(normalizeArabic(p), "iu")) }));

// --- Arabizi: compare words by consonant skeleton (b3atle / ba3atli / ab3atli -> b3tl)
export const azSkeleton = (w: string) => w.toLowerCase().replace(/[aeiouy']/g, "").replace(/(.)\1+/g, "$1");
type Words = [string, string][];
const words = (t: string): Words => (t.match(/[a-z0-9']+/gi) ?? []).map((w) => [w, azSkeleton(w)]);
const first = (ws: Words, test: (w: string, s: string) => boolean) => ws.find(([w, s]) => test(w.toLowerCase(), s))?.[0] ?? null;
const SEND = ["b3t", "3tn", "wrjn"];
const CODE_WORDS = new Set(["code", "codes", "otp", "pin", "ramz"]);
const CODE_SK = new Set(["cd", "kd", "rmz"]);

const ARABIZI: Record<string, (ws: Words) => string | null> = {
  asks_for_code: (ws) => {
    const send = first(ws, (_w, s) => SEND.some((p) => s.startsWith(p)));
    const code = first(ws, (w, s) => CODE_WORDS.has(w) || CODE_SK.has(s));
    return send && code ? `${send} … ${code}` : null;
  },
  prize: (ws) => first(ws, (_w, s) => ["rb7t", "rb7ti", "j2z", "jz", "jyz", "fzt"].includes(s)),
  money_request: (ws) => first(ws, (_w, s) => ["7wl", "sh7n", "ch7n", "df3"].some((p) => s.startsWith(p)) || s === "msr"),
  urgency_threat: (ws) => first(ws, (_w, s) => /^[yt]?skr/.test(s) || s.includes("st3jl")),
  click_link: (ws) => first(ws, (_w, s) => ["kbs", "dght", "2bs"].some((p) => s.startsWith(p))),
};

export function textCueSignals(text: string, hasLink?: boolean): Signal[] {
  if (!text.trim()) return [];
  const norm = normalizeArabic(text);
  const ws = words(norm);
  const hits: [CueDef, string][] = [];
  for (const c of COMPILED) {
    let phrase: string | null = null;
    for (const re of c.res) {
      const m = re.exec(norm);
      if (m) {
        phrase = m[0].trim();
        break;
      }
    }
    if (!phrase && ARABIZI[c.id]) phrase = ARABIZI[c.id](ws);
    if (phrase) hits.push([c, phrase]);
  }
  if (!hits.length) return [];
  const link = hasLink ?? extractUrls(text, 1).urls.length > 0;
  const score = hits.reduce((n, [c]) => n + c.weight, 0) + (link ? 1 : 0);
  const severity = score >= 3 ? "medium" : "low";
  const out = hits.map(([c, phrase]) => sig(`cue_${c.id}`, c.title, `Matched “${phrase}”. ${c.why}`, severity));
  if (score >= DATA.combo_threshold && hits.length + (link ? 1 : 0) >= 2) {
    const parts = [...hits.map(([c]) => c.title.toLowerCase()), ...(link ? ["contains a link"] : [])];
    out.unshift(sig("cue_scam_script", "Matches a common scam script",
      `Together these are the typical shape of a scam message: ${parts.join("; ")}.`, "high"));
  }
  return out;
}
