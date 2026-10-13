// Chat directory (names only, never messages) and the user's selection.
import fs from "node:fs";
import path from "node:path";
import { isIgnoredChat } from "./extract.js";

export class Chats {
  constructor(dir) {
    this.file = path.join(dir, "selection.json");
    this.byId = new Map(); // id -> { id, name, isGroup }
    this.selection = new Set();
    try {
      this.selection = new Set(JSON.parse(fs.readFileSync(this.file, "utf8")));
    } catch {
      /* nothing selected yet */
    }
  }

  upsert(id, name, isGroup = id?.endsWith("@g.us")) {
    if (isIgnoredChat(id)) return;
    const old = this.byId.get(id);
    const clean = typeof name === "string" && name.trim() ? name.trim() : undefined;
    this.byId.set(id, { id, name: clean ?? old?.name ?? null, isGroup: Boolean(isGroup) });
  }

  list() {
    return [...this.byId.values()]
      .map((c) => ({ ...c, name: c.name ?? prettyNumber(c.id), selected: this.selection.has(c.id) }))
      .sort((a, b) => Number(b.selected) - Number(a.selected) || a.name.localeCompare(b.name));
  }

  select(ids) {
    this.selection = new Set(ids.filter((id) => typeof id === "string" && !isIgnoredChat(id)));
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify([...this.selection]));
  }

  nameOf(ids) {
    for (const id of ids) {
      const c = this.byId.get(id);
      if (c?.name) return c.name;
    }
    return prettyNumber(ids[0] ?? "");
  }

  reset() {
    this.byId.clear();
    this.selection = new Set();
  }
}

function prettyNumber(id) {
  const user = String(id).split("@")[0];
  return /^\d+$/.test(user) ? `+${user}` : user;
}
