// WhatsApp connection (Baileys, the unofficial WhatsApp Web multi-device protocol).
//
// Safety rules enforced here:
//  - never sends anything: no replies, no read receipts, no "online" presence
//  - never stores messages: only the login session and the chat selection are on disk
//  - only messages from chats the user selected are passed on (see extract.js)

import fs from "node:fs";
import pino from "pino";
import QRCode from "qrcode";
import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "baileys";
import { chatIdsOf, extractContent, shouldCheck } from "./extract.js";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const log = pino({ level: process.env.LOG_LEVEL ?? "warn" }); // never "debug": it would print messages

export class WhatsApp {
  /** @param {{authDir: string, chats: import("./chats.js").Chats, forward: Function}} opts */
  constructor({ authDir, chats, forward }) {
    this.authDir = authDir;
    this.chats = chats;
    this.forward = forward;
    this.sock = null;
    this.state = "idle"; // idle | connecting | qr | connected
    this.qr = null; // data: URL of the pairing QR
    this.me = null;
    this.error = null;
    this.checked = 0;
    this.retries = 0;
  }

  status() {
    return { state: this.state, qr: this.qr, me: this.me, error: this.error, checked: this.checked,
             selected: this.chats.selection.size };
  }

  hasSession() {
    return fs.existsSync(`${this.authDir}/creds.json`);
  }

  async connect() {
    if (this.sock) return;
    this.state = "connecting";
    this.error = null;
    const { state: auth, saveCreds } = await useMultiFileAuthState(this.authDir);
    let version;
    try {
      ({ version } = await fetchLatestBaileysVersion());
    } catch {
      /* fall back to the version bundled with Baileys */
    }
    const sock = makeWASocket({
      auth,
      version,
      logger: log,
      browser: Browsers.windows("Amaan"), // shown in the phone's "Linked devices" list
      markOnlineOnConnect: false, // keep phone notifications working; never appear "online"
      // Baileys' default light sync is required for a stable session (it carries
      // id mappings). We read only chat names from it and drop every message.
      syncFullHistory: false,
      generateHighQualityLinkPreview: false,
    });
    this.sock = sock;
    sock.ev.on("creds.update", saveCreds);
    sock.ev.on("connection.update", (u) => this.#onConnection(u));

    // Chat names for the picker (no message content is kept).
    sock.ev.on("messaging-history.set", ({ chats, contacts }) => {
      for (const c of chats ?? []) this.chats.upsert(c.id, c.name);
      for (const c of contacts ?? []) this.chats.upsert(c.id, c.name ?? c.notify ?? c.verifiedName);
    });
    sock.ev.on("chats.upsert", (list) => list.forEach((c) => this.chats.upsert(c.id, c.name)));
    sock.ev.on("contacts.upsert", (list) => list.forEach((c) => this.chats.upsert(c.id, c.name ?? c.notify)));
    sock.ev.on("contacts.update", (list) => list.forEach((c) => c.id && this.chats.upsert(c.id, c.name ?? c.notify)));
    sock.ev.on("groups.upsert", (list) => list.forEach((g) => this.chats.upsert(g.id, g.subject, true)));

    sock.ev.on("messages.upsert", ({ messages, type }) => {
      for (const msg of messages) {
        const ids = chatIdsOf(msg.key);
        if (type === "notify" && !msg.key?.fromMe && msg.pushName && !ids[0]?.endsWith("@g.us")) {
          ids.forEach((id) => this.chats.upsert(id, msg.pushName)); // so new chats show up in the picker
        }
        if (shouldCheck(msg, type, this.chats.selection)) {
          this.#check(msg).catch((e) => log.warn({ err: e.message }, "check failed"));
        }
      }
    });
  }

  async #check(msg) {
    const content = extractContent(msg.message);
    if (!content) return;
    const ids = chatIdsOf(msg.key);
    const meta = {
      chatId: ids[0],
      chatName: this.chats.nameOf(ids),
      sender: msg.pushName ?? "",
      timestamp: Number(msg.messageTimestamp ?? Date.now() / 1000),
      kind: content.kind,
      text: content.text,
    };
    let image = null;
    if (content.kind === "image" && content.imageBytes <= MAX_IMAGE_BYTES) {
      image = await downloadMediaMessage(msg, "buffer", {}); // kept in memory only
    }
    this.checked += 1;
    await this.forward(meta, image);
  }

  async #onConnection({ connection, lastDisconnect, qr }) {
    if (qr) {
      this.state = "qr";
      this.qr = await QRCode.toDataURL(qr, { margin: 1, width: 280 });
    }
    if (connection === "open") {
      this.state = "connected";
      this.qr = null;
      this.retries = 0;
      this.me = { id: this.sock.user?.id ?? null, name: this.sock.user?.name ?? null };
      try {
        const groups = await this.sock.groupFetchAllParticipating();
        Object.values(groups).forEach((g) => this.chats.upsert(g.id, g.subject, true));
      } catch {
        /* group names will arrive later */
      }
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      const wasPairing = this.state === "qr";
      this.sock = null;
      this.me = null;
      if (code === DisconnectReason.loggedOut) {
        this.#forget();
        this.error = "WhatsApp was unlinked from the phone.";
      } else if (wasPairing && code === DisconnectReason.timedOut) {
        this.state = "idle"; // QR expired: wait for the user to try again
        this.qr = null;
        this.error = "The QR code expired. Click 'Link WhatsApp' to get a new one.";
      } else if (this.retries < 5) {
        this.retries += 1;
        this.state = "connecting";
        setTimeout(() => this.connect().catch((e) => this.#fail(e)), 2000 * this.retries);
      } else {
        this.#fail(lastDisconnect?.error ?? new Error("connection closed"));
      }
    }
  }

  #fail(e) {
    this.state = "idle";
    this.sock = null;
    this.error = `Could not connect to WhatsApp (${e?.message ?? e}).`;
  }

  #forget() {
    this.state = "idle";
    this.qr = null;
    this.chats.reset();
    fs.rmSync(this.authDir, { recursive: true, force: true }); // session keys + selection
  }

  async logout() {
    try {
      await this.sock?.logout(); // also removes "Amaan" from the phone's Linked devices
    } catch {
      /* already gone */
    }
    this.sock?.end?.(undefined);
    this.sock = null;
    this.#forget();
    this.error = null;
  }
}
