// Sends one message (text, photo or voice note) or one call event to the local
// Amaan backend. Nothing is written to disk; media buffers live only for this request.

const MEDIA = { image: ["image/jpeg", "whatsapp.jpg"], voice: ["audio/ogg", "voice.ogg"] };

export function makeForwarder({ backendUrl, token, fetchImpl = fetch }) {
  return async function forward(meta, media) {
    const form = new FormData();
    form.set("chat_id", meta.chatId ?? "");
    form.set("chat_name", meta.chatName ?? "");
    form.set("sender", meta.sender ?? "");
    form.set("timestamp", String(Math.round(meta.timestamp ?? 0)));
    form.set("kind", meta.kind);
    form.set("text", meta.text ?? "");
    if (meta.callId) form.set("call_id", meta.callId);
    if (meta.ringSeconds != null) form.set("ring_seconds", String(meta.ringSeconds));
    const [type, name] = MEDIA[meta.kind] ?? MEDIA.image;
    if (media) form.set("file", new Blob([media], { type }), name);
    const res = await fetchImpl(`${backendUrl}/whatsapp/ingest`, {
      method: "POST",
      headers: { "X-Bridge-Token": token ?? "" },
      body: form,
    });
    if (!res.ok) throw new Error(`backend answered HTTP ${res.status}`);
  };
}
