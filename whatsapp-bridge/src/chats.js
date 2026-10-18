// Chat directory (ids and names only, never messages) and which chats are watched.
//
// Default watch mode "unknown": every 1:1 chat with a number that is NOT saved
// in the phone's contacts is watched automatically (scams rarely come from
// Mom), plus anything the user ticks; the user can also untick an unknown chat.
// Mode "manual": only the chats the user ticks.
//
// WhatsApp sends contact names mostly once, right after linking, so the
// directory is saved next to the login session (chats.json) to survive
// restarts. "Unlink" deletes the whole folder.
//
// WhatsApp also uses two ids for the same person: a phone id (…@s.whatsapp.net)
// and a privacy id (…@lid). Aliases map both to one entry, preferring the phone id.
import fs from "node:fs";
import path from "node:path";
import { isIgnoredChat } from "./extract.js";

const isPhone = (id) => typeof id === "string" && id.endsWith("@s.whatsapp.net");

export class Chats {
  constructor(dir) {
    this.dir = dir;
    this.selFile = path.join(dir, "selection.json");
    this.dirFile = path.join(dir, "chats.json");
    this.byId = new Map(); // canonical id -> { id, name, isGroup }
    this.alias = new Map(); // other id -> canonical id
    this.mode = "unknown";
    this.include = new Set(); // ticked by the user
    this.exclude = new Set(); // unknown chats the user unticked
    this.saveTimer = null;
    try {
      const sel = JSON.parse(fs.readFileSync(this.selFile, "utf8"));
      if (Array.isArray(sel)) {
        this.include = new Set(sel); // older format: a plain list of ticked chats
      } else {
        this.mode = sel.mode === "manual" ? "manual" : "unknown";
        this.include = new Set(sel.include ?? []);
        this.exclude = new Set(sel.exclude ?? []);
      }
    } catch {
      /* first run: defaults */
    }
    try {
      const saved = JSON.parse(fs.readFileSync(this.dirFile, "utf8"));
      for (const c of saved.chats ?? []) this.byId.set(c.id, c);
      for (const [a, b] of saved.alias ?? []) this.alias.set(a, b);
    } catch {
      /* first run */
    }
  }

  canonical(id) {
    return this.alias.get(id) ?? id;
  }

  /** Record that two ids are the same person (privacy id <-> phone id). */
  link(a, b) {
    if (!a || !b || a === b) return;
    const [keep, drop] = isPhone(b) && !isPhone(a) ? [b, a] : [a, b];
    const k = this.canonical(keep);
    const d = this.canonical(drop);
    if (k === d) return;
    const dropped = this.byId.get(d);
    if (dropped) {
      const kept = this.byId.get(k);
      this.byId.set(k, {
        id: k, name: kept?.name ?? dropped.name, isGroup: kept?.isGroup ?? dropped.isGroup,
        saved: Boolean(kept?.saved || dropped.saved), lastCallAt: Math.max(kept?.lastCallAt ?? 0, dropped.lastCallAt ?? 0) || undefined,
      });
      this.byId.delete(d);
    }
    this.alias.set(d, k);
    for (const [x, y] of this.alias) if (y === d) this.alias.set(x, k);
    for (const set of [this.include, this.exclude]) if (set.delete(d)) set.add(k);
    this.#save();
  }

  /** saved=true means the name comes from the phone's address book. */
  upsert(id, name, isGroup = id?.endsWith("@g.us"), saved = false) {
    if (isIgnoredChat(id)) return;
    const cid = this.canonical(id);
    const old = this.byId.get(cid);
    const clean = typeof name === "string" && name.trim() ? name.trim() : undefined;
    const next = { ...old, id: cid, name: clean ?? old?.name ?? null, isGroup: Boolean(isGroup), saved: Boolean(old?.saved || saved) };
    if (old && old.name === next.name && old.saved === next.saved) return;
    this.byId.set(cid, next);
    this.#save();
  }

  /** An incoming WhatsApp call: remembered so recent callers are easy to spot. */
  recordCall(id, when = Date.now()) {
    if (isIgnoredChat(id)) return;
    const cid = this.canonical(id);
    const old = this.byId.get(cid) ?? { id: cid, name: null, isGroup: false, saved: false };
    this.byId.set(cid, { ...old, lastCallAt: when });
    this.#save();
  }

  /** Use a name only if we have none yet (e.g. the sender's own WhatsApp name). */
  upsertWeak(id, name) {
    const c = this.byId.get(this.canonical(id));
    if (!c?.name) this.upsert(id, name);
  }

  /** A contact record from Baileys: { id, name, notify, lid, phoneNumber }. */
  upsertContact(c) {
    if (!c?.id) return;
    if (c.lid) this.link(c.id, c.lid);
    if (c.phoneNumber) this.link(c.id, c.phoneNumber);
    // c.name is the address-book name (a saved contact); c.notify is the
    // name the person chose for themselves (not saved).
    this.upsert(c.id, c.name ?? c.notify ?? c.verifiedName, false, Boolean(c.name));
  }

  /** Watched automatically in "unknown" mode: a 1:1 chat not saved in contacts. */
  isUnknown(c) {
    return Boolean(c) && !c.isGroup && !c.saved;
  }

  isWatchedId(id) {
    const cid = this.canonical(id);
    if (this.exclude.has(cid)) return false;
    if (this.include.has(cid)) return true;
    if (this.mode !== "unknown") return false;
    const c = this.byId.get(cid);
    return c ? this.isUnknown(c) : !cid.endsWith("@g.us"); // a brand-new number is unknown
  }

  isSelected(ids) {
    return ids.some((id) => this.isWatchedId(id));
  }

  watchedCount() {
    return [...this.byId.keys()].filter((id) => this.isWatchedId(id)).length;
  }

  policy() {
    return { mode: this.mode, include: [...this.include], exclude: [...this.exclude] };
  }

  list() {
    const recent = Date.now() - 7 * 24 * 3600 * 1000;
    return [...this.byId.values()]
      .map((c) => ({
        id: c.id,
        name: c.name ?? prettyId(c.id),
        isGroup: c.isGroup,
        saved: Boolean(c.saved),
        calledRecently: (c.lastCallAt ?? 0) > recent,
        auto: this.mode === "unknown" && this.isUnknown(c), // watched because it's unknown
        selected: this.isWatchedId(c.id),
      }))
      .sort((a, b) => Number(b.selected) - Number(a.selected) || Number(b.calledRecently) - Number(a.calledRecently)
        || a.name.localeCompare(b.name));
  }

  setPolicy({ mode, include = [], exclude = [] }) {
    const clean = (ids) => new Set(ids.filter((id) => typeof id === "string" && !isIgnoredChat(id)).map((id) => this.canonical(id)));
    this.mode = mode === "manual" ? "manual" : "unknown";
    this.include = clean(include);
    this.exclude = clean(exclude);
    for (const id of this.include) this.exclude.delete(id);
    fs.mkdirSync(this.dir, { recursive: true });
    fs.writeFileSync(this.selFile, JSON.stringify(this.policy()));
  }

  /** Older API: tick exactly these chats (manual mode). */
  select(ids) {
    this.setPolicy({ mode: "manual", include: ids });
  }

  /** Add a chat by phone number (for chats WhatsApp never told us about). */
  addNumber(number) {
    const digits = String(number ?? "").replace(/[^\d]/g, "").replace(/^00/, "");
    if (digits.length < 7 || digits.length > 15) throw Object.assign(new Error("Enter a full number with country code, e.g. +961 70 123 456"), { status: 400 });
    const id = this.canonical(`${digits}@s.whatsapp.net`);
    if (!this.byId.has(id)) this.upsert(id, `+${digits}`);
    this.setPolicy({ ...this.policy(), include: [...this.include, id], exclude: [...this.exclude].filter((x) => x !== id) });
    return id;
  }

  nameOf(ids) {
    for (const id of ids) {
      const c = this.byId.get(this.canonical(id));
      if (c?.name) return c.name;
    }
    return prettyId(ids[0] ?? "");
  }

  reset() {
    clearTimeout(this.saveTimer);
    this.saveTimer = null;
    this.byId.clear();
    this.alias.clear();
    this.mode = "unknown";
    this.include = new Set();
    this.exclude = new Set();
  }

  #save() {
    if (this.saveTimer) return;
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      try {
        fs.mkdirSync(this.dir, { recursive: true });
        fs.writeFileSync(this.dirFile, JSON.stringify({ chats: [...this.byId.values()], alias: [...this.alias] }));
      } catch {
        /* folder removed by unlink */
      }
    }, 1000);
    this.saveTimer.unref?.();
  }

  flush() {
    if (!this.saveTimer) return;
    clearTimeout(this.saveTimer);
    this.saveTimer = null;
    fs.mkdirSync(this.dir, { recursive: true });
    fs.writeFileSync(this.dirFile, JSON.stringify({ chats: [...this.byId.values()], alias: [...this.alias] }));
  }
}

function prettyId(id) {
  const [user, server] = String(id).split("@");
  if (server === "lid") return "Unsaved contact";
  return /^\d+$/.test(user) ? `+${user}` : user;
}
