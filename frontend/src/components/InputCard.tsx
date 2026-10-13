import { useRef, useState } from "react";
import { fromDataTransfer, fromFiles, IMAGE_TYPES, type Incoming } from "../lib/dropParse";

interface Props {
  busy: boolean;
  text: string;
  setText: (t: string) => void;
  onInput: (input: Incoming) => void;
  onCamera: () => void;
}

/** One box for everything: type/paste text, drop anything, upload an image, or use the camera. */
export default function InputCard({ busy, text, setText, onInput, onCamera }: Props) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className={`relative rounded-2xl border-2 bg-white p-4 shadow-sm transition-colors ${
        over ? "border-teal-500 bg-teal-50" : "border-slate-200"
      }`}
      onDragEnter={(e) => {
        e.preventDefault();
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault(); // never let the browser open a dropped link or file
        depth.current = 0;
        setOver(false);
        onInput(fromDataTransfer(e.dataTransfer));
      }}
    >
      {over && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-teal-50/90 text-lg font-semibold text-teal-800">
          Drop it here to check it
        </div>
      )}
      <textarea
        dir="auto"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) onInput({ kind: "text", text });
        }}
        placeholder="Paste a suspicious message or link here (Arabic, Arabizi or English)…"
        className="h-28 w-full resize-none rounded-xl bg-slate-50 p-3 text-[15px] focus:bg-white focus:outline-teal-500"
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          disabled={busy || !text.trim()}
          onClick={() => onInput({ kind: "text", text })}
          className="rounded-xl bg-teal-700 px-6 py-2.5 font-semibold text-white hover:bg-teal-600 disabled:opacity-40"
        >
          Check
        </button>
        <span className="px-1 text-sm text-slate-400">or</span>
        <button
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-40"
        >
          🖼 Upload a screenshot / QR
        </button>
        <button
          disabled={busy}
          onClick={onCamera}
          className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-40"
        >
          📷 Scan a QR with the camera
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={IMAGE_TYPES.join(",")}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) onInput(fromFiles(e.target.files));
            e.target.value = "";
          }}
        />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        You can also drag &amp; drop anything here, or press Ctrl+V anywhere on the page. Amaan never opens the links it checks.
      </p>
    </div>
  );
}
