import { useRef, useState } from "react";
import { fromDataTransfer, fromFiles, IMAGE_TYPES, type Incoming } from "../lib/dropParse";

interface Props {
  busy: boolean;
  onInput: (input: Incoming) => void;
  onOpenCamera: () => void;
}

export default function DropZone({ busy, onInput, onOpenCamera }: Props) {
  const [over, setOver] = useState(false);
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const depth = useRef(0);

  return (
    <div
      className={`rounded-2xl border-2 border-dashed p-6 transition-colors ${
        over ? "border-teal-500 bg-teal-50" : "border-slate-300 bg-white"
      }`}
      onDragEnter={(e) => {
        e.preventDefault();
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault(); // stop the browser from opening/navigating to the dropped item
        depth.current = 0;
        setOver(false);
        onInput(fromDataTransfer(e.dataTransfer));
      }}
    >
      <div className="text-center">
        <svg viewBox="0 0 24 24" className="mx-auto h-10 w-10 text-teal-700" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M12 2l8 3.5v6c0 5-3.4 9-8 10.5C7.4 20.5 4 16.5 4 11.5v-6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
        <p className="mt-2 text-lg font-semibold">Drop a suspicious link, message, screenshot or QR code here</p>
        <p className="text-sm text-slate-500">
          or press <kbd className="rounded border bg-slate-100 px-1">Ctrl</kbd>+<kbd className="rounded border bg-slate-100 px-1">V</kbd> anywhere to paste.
          Nothing is opened: links are checked inside an isolated sandbox.
        </p>
      </div>

      <textarea
        dir="auto"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) onInput({ kind: "text", text });
        }}
        placeholder="…or type / paste the message here (Arabic, Arabizi or English)"
        className="mt-4 h-24 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm focus:border-teal-500 focus:outline-none"
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          disabled={busy || !text.trim()}
          onClick={() => onInput({ kind: "text", text })}
          className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-40"
        >
          Check text
        </button>
        <button
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-40"
        >
          Upload image…
        </button>
        <button
          disabled={busy}
          onClick={onOpenCamera}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-40"
        >
          Scan QR with camera
        </button>
        {text && (
          <button onClick={() => setText("")} className="ml-auto text-sm text-slate-500 hover:text-slate-800">
            Clear
          </button>
        )}
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
    </div>
  );
}
