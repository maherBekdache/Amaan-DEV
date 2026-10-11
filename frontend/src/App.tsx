import { useCallback, useEffect, useState } from "react";
import CameraScanner from "./components/CameraScanner";
import DropZone from "./components/DropZone";
import HistoryList from "./components/HistoryList";
import ResultPanel from "./components/ResultPanel";
import { analyzeImage, analyzeText, ApiError, getHealth } from "./lib/api";
import { fromDataTransfer, type Incoming } from "./lib/dropParse";
import { addToHistory, clearHistory, loadHistory, type HistoryEntry } from "./lib/history";
import type { Evidence, Health } from "./types";

export default function App() {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const [health, setHealth] = useState<Health | null | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    const tick = () => getHealth().then((h) => alive && setHealth(h));
    tick();
    const id = setInterval(tick, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const run = useCallback(async (label: string, job: () => Promise<Evidence>) => {
    setBusy(label);
    setError(null);
    try {
      const ev = await job();
      setResult(ev);
      setHistory(addToHistory(ev));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong while analyzing.");
    } finally {
      setBusy(null);
    }
  }, []);

  const handleInput = useCallback(
    (input: Incoming) => {
      if (busy) return;
      switch (input.kind) {
        case "image":
          setCamera(false);
          run("Looking for QR codes…", () => analyzeImage(input.file, "image", input.file.name));
          break;
        case "text":
          run("Checking links…", () => analyzeText({ text: input.text, html: input.html, uri_list: input.uri_list }));
          break;
        case "unsupported":
          setError(input.reason);
          break;
        case "empty":
          setError("Nothing to analyze was found in what you dropped or pasted.");
          break;
      }
    },
    [busy, run],
  );

  // Ctrl+V anywhere on the page (except while typing in the text box).
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
      e.preventDefault();
      handleInput(fromDataTransfer(e.clipboardData));
    };
    // A drop that misses the drop zone must never make the browser open the
    // dropped link or file, so catch drops on the whole window too.
    const stopNav = (e: DragEvent) => e.preventDefault();
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      if (!(e.target as HTMLElement)?.closest?.("[data-dropzone]")) handleInput(fromDataTransfer(e.dataTransfer));
    };
    window.addEventListener("paste", onPaste);
    window.addEventListener("dragover", stopNav);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("dragover", stopNav);
      window.removeEventListener("drop", onDrop);
    };
  }, [handleInput]);

  return (
    <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-6 px-4 py-6">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 24 24" className="h-8 w-8 text-teal-700" fill="currentColor">
            <path d="M12 2l8 3.5v6c0 5-3.4 9-8 10.5C7.4 20.5 4 16.5 4 11.5v-6z" />
          </svg>
          <div>
            <h1 className="text-xl font-bold leading-tight">Amaan <span className="font-normal text-slate-400">أمان</span></h1>
            <p className="text-xs text-slate-500">Check before you click. Everything is analyzed on this computer.</p>
          </div>
        </div>
        <StatusPill health={health} />
      </header>

      <main className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <div data-dropzone>
            {camera ? (
              <CameraScanner
                onClose={() => setCamera(false)}
                onCapture={(frame) => {
                  setCamera(false);
                  run("Analyzing camera frame…", () => analyzeImage(frame, "camera", "camera.png"));
                }}
              />
            ) : (
              <DropZone busy={!!busy} onInput={handleInput} onOpenCamera={() => setCamera(true)} />
            )}
          </div>

          {busy && (
            <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
              {busy} Links are checked in URL.vet's sandbox; this can take up to 15 seconds.
            </div>
          )}
          {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
          {result && !busy && <ResultPanel ev={result} />}
        </div>

        <HistoryList entries={history} onClear={() => setHistory(clearHistory())} />
      </main>

      <footer className="mt-auto text-center text-xs text-slate-400">
        Amaan prototype · AUB FYP · Results are guidance, not a guarantee. Never share verification codes.
      </footer>
    </div>
  );
}

function StatusPill({ health }: { health: Health | null | undefined }) {
  if (health === undefined) return null;
  const [color, text] = !health
    ? ["bg-red-500", "Backend offline"]
    : health.urlvet.reachable && health.urlvet.mock
      ? ["bg-fuchsia-500", "MOCK URL.vet: fake link verdicts (dev only)"]
      : health.urlvet.reachable
      ? ["bg-emerald-500", "Link sandbox (URL.vet) online"]
      : ["bg-amber-500", "URL.vet offline: local checks only"];
  return (
    <span className="ml-auto flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {text}
    </span>
  );
}
