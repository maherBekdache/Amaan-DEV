// Links to other sites' own rating of a link (VirusTotal, Safe Browsing, URLVoid, …).
// Port of backend/amaan/lookups.py. Only addresses are built; nothing is fetched.
import data from "./data/lookups.json";

export interface Lookup { id: string; name: string; about: string; href: string }

// Same escaping as Python's urllib.parse.quote (safe="" / safe=".-").
const quote = (s: string, safe = "") =>
  encodeURIComponent(s).replace(/[!'()*~]/g, (c) => (safe.includes(c) || c === "~" ? c : "%" + c.charCodeAt(0).toString(16).toUpperCase()));

export function lookupLinks(url: string, hostAscii: string): Lookup[] {
  const enc = quote(url.includes("://") ? url : "http://" + url); // the sites expect a full URL
  const values: Record<string, string> = { "{url}": enc, "{url2}": quote(enc), "{host}": quote(hostAscii, ".-") };
  return data.sites.map((s) => ({
    id: s.id, name: s.name, about: s.about,
    href: Object.entries(values).reduce((h, [k, v]) => h.split(k).join(v), s.template),
  }));
}
