import { useCallback, useEffect, useRef, useState } from "react";
import CameraScanner from "./components/CameraScanner";
import Examples, { loadExampleImage, type Example } from "./components/Examples";
import HistoryList from "./components/HistoryList";
import InputCard from "./components/InputCard";
import Verdict, { type Checked } from "./components/Verdict";
import WhatsAppPanel from "./components/WhatsAppPanel";
import { analyzeImage, analyzeText, ApiError, getHealth, importChat } from "./lib/api";
import { fromDataTransfer, type Incoming } from "./lib/dropParse";
import { addToHistory, clearHistory, loadHistory, type HistoryEntry } from "./lib/history";
import type { Evidence, Health, ImportReport } from "./types";

export default function App() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const [result, setResult] = useState<Evidence | null>(null);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const [tab, setTab] = useState<"check" | "whatsapp">("check");
  const [importing, setImporting] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = () => getHealth().then((h) => alive && setHealth(h));
    tick();
    const id = setInterval(tick, 15_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const showChecked = useCallback((c: Checked) => {
    setChecked((old) => {
      if (old?.imageUrl) URL.revokeObjectURL(old.imageUrl);
      return c;
    });
  }, []);

  const run = useCallback(async (job: () => Promise<Evidence>) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const ev = await job();
      setResult(ev);
      setHistory(addToHistory(ev));
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Is Amaan still running?");
    } finally {
      setBusy(false);
    }
  }, []);

  const checkImage = useCallback(
    (file: Blob, source: "image" | "camera", name: string) => {
      setCamera(false);
      setText(""); // the text box would otherwise still show the previous message
      showChecked({ kind: "image", imageUrl: URL.createObjectURL(file) });
      run(() => analyzeImage(file, source, name));
    },
    [run, showChecked],
  );

  const runImport = useCallback(async (file: File) => {
    setTab("whatsapp");
    setImporting(true);
    setReport(null);
    setError(null);
    try {
      setReport(await importChat(file));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read this chat export.");
    } finally {
      setImporting(false);
    }
  }, []);

  const handleInput = useCallback(
    (input: Incoming) => {
      if (busy || importing) return;
      if (input.kind === "chat_export") runImport(input.file);
      else if (input.kind === "image") {
        setTab("check");
        checkImage(input.file, "image", input.file.name);
      }
      else if (input.kind === "text") {
        const shown = input.text || input.uri_list || "";
        if (input.text) setText(input.text);
        showChecked({ kind: "text", text: shown });
        run(() => analyzeText({ text: input.text, html: input.html, uri_list: input.uri_list }));
      } else if (input.kind === "unsupported") setError(input.reason);
      else setError("Nothing to check was found in what you dropped or pasted.");
    },
    [busy, importing, checkImage, run, runImport, showChecked],
  );

  const pickExample = useCallback(
    async (e: Example) => {
      if (e.kind === "text") handleInput({ kind: "text", text: e.text });
      else checkImage(await loadExampleImage(e.file), "image", e.file);
    },
    [handleInput, checkImage],
  );

  // Ctrl+V anywhere (outside the text box) and drops outside the card.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
      e.preventDefault();
      handleInput(fromDataTransfer(e.clipboardData));
    };
    const stop = (e: DragEvent) => e.preventDefault(); // never navigate to a dropped link
    window.addEventListener("paste", onPaste);
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => {
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("dragover", stop);
      window.removeEventListener("drop", stop);
    };
  }, [handleInput]);

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col gap-5 px-4 py-6">
      <header className="flex items-center gap-3">
        <svg viewBox="0 0 24 24" className="h-10 w-10 text-teal-700" fill="currentColor" aria-hidden>
          <path d="M12 2l8 3.5v6c0 5-3.4 9-8 10.5C7.4 20.5 4 16.5 4 11.5v-6z" />
        </svg>
        <div>
          <h1 className="text-2xl font-bold leading-tight">
            Amaan <span className="font-normal text-slate-400">أمان</span>
          </h1>
          <p className="text-sm text-slate-500">Is this message, link or QR code a scam? Check before you click.</p>
        </div>
        <Status health={health} />
      </header>

      <nav className="flex gap-1 rounded-xl bg-slate-200/70 p-1 text-sm font-medium">
        {(["check", "whatsapp"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 rounded-lg px-4 py-2 ${tab === t ? "bg-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
          >
            {t === "check" ? "🔍 Check something" : "💬 WhatsApp"}
          </button>
        ))}
      </nav>

      {tab === "whatsapp" ? (
        <>
          {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>}
          <WhatsAppPanel report={report} importing={importing} onImport={runImport} />
        </>
      ) : (
        <>
        {camera ? (
          <CameraScanner onClose={() => setCamera(false)} onCapture={(frame) => checkImage(frame, "camera", "camera.png")} />
        ) : (
          <InputCard busy={busy} text={text} setText={setText} onInput={handleInput} onCamera={() => setCamera(true)} />
        )}

        <Examples disabled={busy} onPick={pickExample} />

        <div ref={resultRef} className="scroll-mt-4">
          {busy && (
            <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-5">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
              <span>Checking… links are tested in a safe sandbox, this can take up to 15 seconds.</span>
            </div>
          )}
          {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>}
          {result && !busy && <Verdict ev={result} checked={checked} />}
        </div>
        </>
      )}

      <HistoryList entries={history} onClear={() => setHistory(clearHistory())} />

      <footer className="mt-auto pt-4 text-center text-xs text-slate-400">
        Everything is analyzed on this computer. Amaan gives guidance, not guarantees.
      </footer>
    </div>
  );
}

function Status({ health }: { health: Health | null | undefined }) {
  if (health === undefined) return null;
  const [dot, text, title] = !health
    ? ["bg-red-500", "Offline", "Amaan's backend is not running."]
    : health.urlvet.reachable && health.urlvet.mock
      ? ["bg-fuchsia-500", "MOCK mode", "Link verdicts are fake (development only)."]
      : health.urlvet.reachable
        ? ["bg-emerald-500", "Ready", "All checks available."]
        : ["bg-amber-500", "Link checker starting…", "URL.vet is not reachable yet; links get basic checks only."];
  return (
    <span title={title} className="ml-auto flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
    </span>
  );
}
