/**
 * Turn a drop or paste event into something we can analyze.
 *
 * Security: nothing here fetches, opens or renders what was dropped. HTML is
 * passed to the backend as a string and parsed there; it is never inserted
 * into the page. Remote image URLs are never downloaded.
 */

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const AUDIO_EXT = /\.(opus|ogg|m4a|mp3|wav|aac)$/i;

export type Incoming =
  | { kind: "image"; file: File }
  | { kind: "text"; text: string; html?: string; uri_list?: string }
  | { kind: "unsupported"; reason: string }
  | { kind: "empty" };

export function fromFiles(files: FileList | File[]): Incoming {
  const list = Array.from(files);
  if (list.length === 0) return { kind: "empty" };
  const image = list.find((f) => IMAGE_TYPES.includes(f.type));
  if (image) return { kind: "image", file: image };
  const f = list[0];
  if (f.type.startsWith("audio/") || AUDIO_EXT.test(f.name)) {
    return { kind: "unsupported", reason: "Voice notes are coming in the next milestone." };
  }
  if (f.type.startsWith("image/")) {
    return { kind: "unsupported", reason: `"${f.type}" images are not supported. Use PNG, JPG or WebP.` };
  }
  if (f.type === "text/plain" || /\.txt$/i.test(f.name)) {
    return { kind: "unsupported", reason: "Text files: open the file and paste its text instead (chat import comes later)." };
  }
  return { kind: "unsupported", reason: `Can't analyze "${f.name}" (${f.type || "unknown type"}).` };
}

export function fromDataTransfer(dt: DataTransfer | null): Incoming {
  if (!dt) return { kind: "empty" };

  // 1) Real files win (screenshots, saved QR images, files from Explorer/WhatsApp).
  const files: File[] = Array.from(dt.files ?? []);
  if (files.length === 0 && dt.items) {
    for (const item of Array.from(dt.items)) {
      if (item.kind === "file") {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
  }
  if (files.length > 0) return fromFiles(files);

  // 2) Links and text. Keep all three flavours: the backend compares them
  //    (e.g. link text that differs from the real target).
  const uriList = safeGet(dt, "text/uri-list");
  const html = safeGet(dt, "text/html");
  const text = safeGet(dt, "text/plain");
  if (!uriList && !html && !text) return { kind: "empty" };
  return {
    kind: "text",
    text: text ?? "",
    ...(html ? { html } : {}),
    ...(uriList ? { uri_list: uriList } : {}),
  };
}

function safeGet(dt: DataTransfer, type: string): string | undefined {
  try {
    const v = dt.getData(type);
    return v && v.trim() ? v : undefined;
  } catch {
    return undefined;
  }
}
