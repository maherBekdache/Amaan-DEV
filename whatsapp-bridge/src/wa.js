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

const MAX_MEDIA_BYTES = 10 * 1024 * 1024; // photos and voice notes larger than this are not downloaded
const log = pino({ level: process.env.LOG_LEVEL ?? "warn" }); // never "debug": it would print messages

export class WhatsApp {
  /** @param {{authDir: string, chats: import("./chats.js").Chats, forward: Function}} opts */
  constructor({ authDir, chats, forward, makeSocket = makeWASocket, loadAuth = useMultiFileAuthState, fetchVersion = fetchLatestBaileysVersion }) {
    this.makeSocket = makeSocket; // injectable for tests
    this.loadAuth = loadAuth;
    this.fetchVersion = fetchVersion;
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
    this.calls = new Map(); // call id -> { id, startedAt, video } while it rings
    this.connecting = null; // the pending connect() promise
    this.watchdog = null;
    this.retryTimer = null;
  }

  status() {
    return { state: this.state, qr: this.qr, me: this.me, error: this.error, checked: this.checked,
             selected: this.chats.watchedCount(), mode: this.chats.mode };
  }

  hasSession() {
    return fs.existsSync(`${this.authDir}/creds.json`);
  }

  /** Start (or resume) the WhatsApp connection. Safe to call repeatedly. */
  connect() {
    if (this.sock || this.connecting) return this.connecting ?? Promise.resolve();
    this.connecting = this.#open()
      .catch((e) => this.#fail(e))
      .finally(() => {
        this.connecting = null;
      });
    return this.connecting;
  }

  async #open() {
    this.state = "connecting";
    this.error = null;
    this.#startWatchdog();
    const { state: auth, saveCreds } = await this.loadAuth(this.authDir);
    let version;
    try {
      // Never let this lookup hang the connection.
      ({ version } = await Promise.race([
        this.fetchVersion(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 5000)),
      ]));
    } catch {
      /* fall back to the version bundled with Baileys */
    }
    const sock = this.makeSocket({
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
    sock.ev.on("messaging-history.set", ({ chats, contacts, lidPnMappings }) => {
      for (const m of lidPnMappings ?? []) this.chats.link(m.pn, m.lid);
      for (const c of contacts ?? []) this.chats.upsertContact(c);
      for (const c of chats ?? []) this.chats.upsert(c.id, c.name);
    });
    sock.ev.on("lid-mapping.update", ({ lid, pn }) => this.chats.link(pn, lid));
    sock.ev.on("chats.upsert", (list) => list.forEach((c) => this.chats.upsert(c.id, c.name)));
    sock.ev.on("contacts.upsert", (list) => list.forEach((c) => this.chats.upsertContact(c)));
    sock.ev.on("contacts.update", (list) => list.forEach((c) => this.chats.upsertContact(c)));
    sock.ev.on("groups.upsert", (list) => list.forEach((g) => this.chats.upsert(g.id, g.subject, true)));

    // Calls: WhatsApp only tells a linked device that a call rings, is answered
    // or ends (no audio). We never answer or reject the call.
    sock.ev.on("call", (calls) => (calls ?? []).forEach((c) => this.#onCall(c)));

    sock.ev.on("messages.upsert", ({ messages, type }) => {
      for (const msg of messages) {
        const ids = chatIdsOf(msg.key);
        if (ids.length === 2) this.chats.link(ids[0], ids[1]); // privacy id <-> phone id
        if (type === "notify" && !msg.key?.fromMe && !ids[0]?.endsWith("@g.us")) {
          this.chats.upsertWeak(ids[0], msg.pushName); // new chats show up in the picker
        }
        if (shouldCheck(msg, type, this.chats)) {
          this.#check(msg).catch((e) => log.warn({ err: e.message }, "check failed"));
        }
      }
    });
  }

  /** An unknown caller is reported when the call starts, and again when it ends
   *  unanswered (a short ring from an unknown number is the "Wangiri" trick). */
  #onCall(c) {
    if (c.isGroup) return;
    if (c.callerPn) this.chats.link(c.callerPn, c.from);
    const id = this.chats.canonical(c.callerPn ?? c.from);
    const at = c.date ? new Date(c.date).getTime() : Date.now();
    if (c.status === "offer") {
      this.chats.recordCall(id);
      if (!this.chats.isWatchedId(id)) return;
      this.calls.set(c.id, { startedAt: at, video: Boolean(c.isVideo) });
      this.checked += 1;
      this.#report({ chatId: id, kind: c.isVideo ? "video_call" : "call", callId: c.id, timestamp: at / 1000 });
    } else if (c.status === "accept") {
      this.calls.delete(c.id); // answered on the phone: nothing more to report
    } else if (["timeout", "reject", "terminate"].includes(c.status) && this.calls.has(c.id)) {
      const call = this.calls.get(c.id);
      this.calls.delete(c.id);
      this.#report({ chatId: id, kind: "missed_call", callId: c.id, timestamp: call.startedAt / 1000,
                     ringSeconds: Math.max(0, Math.round((at - call.startedAt) / 1000)) });
    }
  }

  #report(meta) {
    this.forward({ chatName: this.chats.nameOf([meta.chatId]), sender: "", text: "", ...meta }, null)
      .catch((e) => log.warn({ err: e.message }, "call report failed"));
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
    const size = content.kind === "image" ? content.imageBytes : content.kind === "voice" ? content.audioBytes : null;
    let media = null;
    if (size != null && size <= MAX_MEDIA_BYTES) {
      media = await downloadMediaMessage(msg, "buffer", {}); // kept in memory only
    }
    this.checked += 1;
    await this.forward(meta, media);
  }

  async #onConnection({ connection, lastDisconnect, qr }) {
    if (qr) {
      clearTimeout(this.watchdog); // waiting for the user to scan is not a hang
      this.state = "qr";
      this.qr = await QRCode.toDataURL(qr, { margin: 1, width: 280 });
    }
    if (connection === "open") {
      clearTimeout(this.watchdog);
      this.state = "connected";
      this.qr = null;
      this.error = null;
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
      const R = DisconnectReason;
      if (code === R.loggedOut || code === R.badSession) {
        this.#stop();
        this.#forget();
        this.error = code === R.loggedOut
          ? "WhatsApp was unlinked from the phone. Click 'Link WhatsApp' to link again."
          : "The saved WhatsApp login was damaged and has been cleared. Click 'Link WhatsApp' to link again.";
      } else if (code === R.forbidden) {
        this.#stop();
        this.state = "idle";
        this.error = "WhatsApp refused this connection (the number may be restricted). Try another test number.";
      } else if (code === R.connectionReplaced) {
        this.#stop();
        this.state = "idle";
        this.error = "Another WhatsApp Web session took over this link (e.g. a second copy of Amaan). Close it, then click 'Link WhatsApp'.";
      } else if (wasPairing && code === R.timedOut) {
        this.#stop();
        this.state = "idle"; // QR expired: wait for the user to try again
        this.qr = null;
        this.error = "The QR code expired. Click 'Link WhatsApp' to get a new one.";
      } else if (code === R.restartRequired) {
        this.connect(); // normal right after scanning the QR
      } else if (this.retries < 5) {
        this.retries += 1;
        this.state = "connecting";
        this.error = `Connection dropped (${reasonText(code)}). Retrying ${this.retries}/5…`;
        this.retryTimer = setTimeout(() => this.connect(), 2000 * this.retries);
      } else {
        this.#fail(lastDisconnect?.error ?? new Error(reasonText(code)));
      }
    }
  }

  #fail(e) {
    this.#stop();
    this.state = "idle";
    this.error = `Could not connect to WhatsApp (${e?.message ?? e}). Check the internet connection, then click 'Link WhatsApp'.`;
  }

  /** If we are still not connected after 90 s, give up instead of spinning forever. */
  #startWatchdog() {
    clearTimeout(this.watchdog);
    this.watchdog = setTimeout(() => {
      if (this.state === "connecting") this.#fail(new Error("no answer from WhatsApp after 90 s"));
    }, 90_000);
    this.watchdog.unref?.();
  }

  #stop() {
    clearTimeout(this.watchdog);
    clearTimeout(this.retryTimer); // a pending retry must not revive a stopped connection
    this.retries = 0;
    this.calls.clear();
    try {
      this.sock?.end?.(undefined);
    } catch {
      /* already closed */
    }
    this.sock = null;
  }

  #forget() {
    this.state = "idle";
    this.qr = null;
    this.chats.reset();
    fs.rmSync(this.authDir, { recursive: true, force: true }); // session keys + selection
  }

  /** Unlink (or "start over" when stuck): removes the login, chat list and selection. */
  async logout() {
    try {
      await Promise.race([this.sock?.logout(), new Promise((r) => setTimeout(r, 5000))]); // removes "Amaan" from Linked devices
    } catch {
      /* already gone */
    }
    this.#stop();
    this.#forget();
    this.error = null;
  }
}

function reasonText(code) {
  const names = { 401: "logged out", 403: "refused", 408: "timed out", 411: "device mismatch", 428: "connection closed",
                  440: "replaced by another session", 500: "bad session", 503: "WhatsApp unavailable", 515: "restart required" };
  return names[code] ? `${names[code]}, code ${code}` : `code ${code ?? "unknown"}`;
}
