// Pure helpers: decide whether a WhatsApp message should be checked, and
// pull out only what Amaan needs (text and/or an image). No I/O here.

const WRAPPERS = [
  "ephemeralMessage",
  "viewOnceMessage",
  "viewOnceMessageV2",
  "viewOnceMessageV2Extension",
  "documentWithCaptionMessage",
  "editedMessage",
];

/** Remove WhatsApp's wrapper layers (disappearing, view-once, ...). */
export function unwrap(message) {
  let m = message;
  for (let i = 0; i < 5 && m; i++) {
    const key = WRAPPERS.find((k) => m[k]?.message);
    if (!key) break;
    m = m[key].message;
  }
  return m ?? null;
}

/**
 * @returns {{kind: "text"|"image"|"voice", text: string, imageBytes?: number, audioBytes?: number, seconds?: number} | null}
 *   null when there is nothing to check (stickers, reactions, ...).
 */
export function extractContent(message) {
  const m = unwrap(message);
  if (!m) return null;
  const text = (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    ""
  ).trim();
  if (m.imageMessage) return { kind: "image", text, imageBytes: Number(m.imageMessage.fileLength ?? 0) };
  if (m.audioMessage) {
    return { kind: "voice", text: "", audioBytes: Number(m.audioMessage.fileLength ?? 0), seconds: Number(m.audioMessage.seconds ?? 0) };
  }
  if (text) return { kind: "text", text };
  return null;
}

/** The chat ids a message may be addressed by (WhatsApp now mixes phone ids and "LID" ids). */
export function chatIdsOf(key) {
  return [key?.remoteJid, key?.remoteJidAlt].filter(Boolean);
}

export function isIgnoredChat(jid) {
  return !jid || jid === "status@broadcast" || jid.endsWith("@newsletter") || jid.endsWith("@broadcast");
}

/** Only new, incoming messages from chats the user selected. */
export function shouldCheck(msg, upsertType, selection) {
  // `selection` is a Set of chat ids, or anything with isSelected(ids) (see Chats).
  if (upsertType !== "notify") return false; // skip history sync and our own appends
  if (!msg?.key || msg.key.fromMe) return false; // never look at what the user sends
  const ids = chatIdsOf(msg.key);
  if (ids.some(isIgnoredChat)) return false;
  return typeof selection.isSelected === "function" ? selection.isSelected(ids) : ids.some((id) => selection.has(id));
}
