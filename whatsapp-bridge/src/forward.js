// Sends one message's text/image to the local Amaan backend for analysis.
// Nothing is written to disk; the image buffer lives only for this request.

export function makeForwarder({ backendUrl, token, fetchImpl = fetch }) {
  return async function forward(meta, image) {
    const form = new FormData();
    form.set("chat_id", meta.chatId ?? "");
    form.set("chat_name", meta.chatName ?? "");
    form.set("sender", meta.sender ?? "");
    form.set("timestamp", String(Math.round(meta.timestamp ?? 0)));
    form.set("kind", meta.kind);
    form.set("text", meta.text ?? "");
    if (image) form.set("file", new Blob([image], { type: "image/jpeg" }), "whatsapp.jpg");
    const res = await fetchImpl(`${backendUrl}/whatsapp/ingest`, {
      method: "POST",
      headers: { "X-Bridge-Token": token ?? "" },
      body: form,
    });
    if (!res.ok) throw new Error(`backend answered HTTP ${res.status}`);
  };
}
