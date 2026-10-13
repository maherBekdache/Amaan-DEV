// Chat directory (ids and names only, never messages) and the user's selection.
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
    this.selection = new Set();
    this.saveTimer = null;
    try {
      this.selection = new Set(JSON.parse(fs.readFileSync(this.selFile, "utf8")));
    } catch {
      /* nothing selected yet */
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
      this.byId.set(k, { id: k, name: kept?.name ?? dropped.name, isGroup: kept?.isGroup ?? dropped.isGroup });
      this.byId.delete(d);
    }
    this.alias.set(d, k);
    for (const [x, y] of this.alias) if (y === d) this.alias.set(x, k);
    if (this.selection.delete(d)) this.selection.add(k);
    this.#save();
  }

  upsert(id, name, isGroup = id?.endsWith("@g.us")) {
    if (isIgnoredChat(id)) return;
    const cid = this.canonical(id);
    const old = this.byId.get(cid);
    const clean = typeof name === "string" && name.trim() ? name.trim() : undefined;
    if (old && (old.name === (clean ?? old.name))) return;
    this.byId.set(cid, { id: cid, name: clean ?? old?.name ?? null, isGroup: Boolean(isGroup) });
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
    this.upsert(c.id, c.name ?? c.notify ?? c.verifiedName);
  }

  isSelected(ids) {
    return ids.some((id) => this.selection.has(id) || this.selection.has(this.canonical(id)));
  }

  list() {
    return [...this.byId.values()]
      .map((c) => ({ ...c, name: c.name ?? prettyId(c.id), selected: this.selection.has(c.id) }))
      .sort((a, b) => Number(b.selected) - Number(a.selected) || a.name.localeCompare(b.name));
  }

  select(ids) {
    this.selection = new Set(ids.filter((id) => typeof id === "string" && !isIgnoredChat(id)).map((id) => this.canonical(id)));
    fs.mkdirSync(this.dir, { recursive: true });
    fs.writeFileSync(this.selFile, JSON.stringify([...this.selection]));
  }

  /** Add a chat by phone number (for chats WhatsApp never told us about). */
  addNumber(number) {
    const digits = String(number ?? "").replace(/[^\d]/g, "").replace(/^00/, "");
    if (digits.length < 7 || digits.length > 15) throw Object.assign(new Error("Enter a full number with country code, e.g. +961 70 123 456"), { status: 400 });
    const id = this.canonical(`${digits}@s.whatsapp.net`);
    if (!this.byId.has(id)) this.upsert(id, `+${digits}`);
    this.select([...this.selection, id]);
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
    this.selection = new Set();
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
