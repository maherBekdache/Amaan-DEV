import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, wa } from "../lib/api";
import type { ImportReport, WaAlert, WaChat, WaPolicy, WaStatus } from "../types";
import { RiskBadge } from "./ItemDetails";
import Verdict from "./Verdict";

interface Props {
  report: ImportReport | null;
  importing: boolean;
  onImport: (file: File) => void;
}

/** WhatsApp tab: (1) import an exported chat, (2) watch selected chats live. */
export default function WhatsAppPanel({ report, importing, onImport }: Props) {
  return (
    <div className="space-y-5">
      <ImportCard report={report} importing={importing} onImport={onImport} />
      <LiveCard />
    </div>
  );
}

// --- 1. Import an exported chat (no WhatsApp connection at all) -----------------

function ImportCard({ report, importing, onImport }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Check a whole chat</h2>
      <p className="mt-1 text-sm text-slate-600">
        In WhatsApp on your phone: open the chat → <b>⋮</b> (or the contact name on iPhone) → <b>More</b> →{" "}
        <b>Export chat</b> → send the file to this computer. Then upload it here, or drop it anywhere on this page.
      </p>
      <button
        disabled={importing}
        onClick={() => fileRef.current?.click()}
        className="mt-3 rounded-xl bg-teal-700 px-5 py-2.5 font-semibold text-white hover:bg-teal-600 disabled:opacity-40"
      >
        {importing ? "Checking the chat…" : "Upload exported chat (.txt or .zip)"}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".txt,.zip,text/plain,application/zip"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onImport(f);
          e.target.value = "";
        }}
      />
      <p className="mt-2 text-xs text-slate-400">Safest option: no WhatsApp login. The file is analyzed in memory and not kept.</p>
      {report && <ImportResult report={report} />}
    </section>
  );
}

function ImportResult({ report }: { report: ImportReport }) {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge level={report.risk_level} />
        <span className="font-semibold">{report.title}</span>
        <span className="text-sm text-slate-500">
          {report.messages_total} messages · {report.links_found} link{report.links_found === 1 ? "" : "s"} ({report.links_checked} sandbox-checked) ·{" "}
          {report.images_checked} photos scanned
        </span>
      </div>
      {report.warnings.map((w, i) => (
        <p key={i} className="rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-900">⚠ {w}</p>
      ))}
      {report.findings.length === 0 ? (
        <p className="text-sm text-emerald-800">✅ No suspicious messages found in this chat.</p>
      ) : (
        <ul className="space-y-2">
          {report.findings.map((f, i) => (
            <li key={i} className="rounded-xl border border-slate-200">
              <button className="flex w-full items-center gap-3 p-3 text-left" onClick={() => setOpen(open === i ? null : i)}>
                <RiskBadge level={f.evidence.risk_level} />
                <span className="shrink-0 text-sm font-medium">{f.sender || "Photo"}</span>
                <span dir="auto" className="min-w-0 flex-1 truncate text-sm text-slate-600">{f.text}</span>
                <span className="shrink-0 text-xs text-slate-400">{f.date} {f.time} {open === i ? "▴" : "▾"}</span>
              </button>
              {open === i && (
                <div className="border-t border-slate-100 p-3">
                  <Verdict ev={f.evidence} checked={{ kind: "text", text: f.text }} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- 2. Live: link WhatsApp, choose chats, see alerts --------------------------

function LiveCard() {
  const [status, setStatus] = useState<WaStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => wa.status().then(setStatus, () => setStatus({ enabled: false })), []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Watch chats live</h2>
      <p className="mt-1 text-sm text-slate-600">
        Link WhatsApp like WhatsApp Web, then choose which chats Amaan should watch. New links and photos in those
        chats are checked automatically. Amaan never replies, never marks messages as read and never saves chats.
      </p>
      <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
        ⚠ This uses an unofficial WhatsApp connection. WhatsApp may block numbers that use it. Use a{" "}
        <b>test number</b>, not your main one.
      </p>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}

      <div className="mt-4">
        {!status ? null : !status.enabled ? (
          <p className="text-sm text-slate-600">
            Live watching is off. To turn it on, close Amaan with <b>stop.bat</b> and start it with{" "}
            <b>start-whatsapp.bat</b>.
          </p>
        ) : status.state === "connected" ? (
          <Connected status={status} onLogout={() => act(wa.logout)} busy={busy} />
        ) : status.state === "qr" && status.qr ? (
          <div className="flex flex-wrap items-center gap-5">
            <img src={status.qr} alt="WhatsApp pairing QR code" className="h-56 w-56 rounded-lg border" />
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              <li>Open WhatsApp on the phone (test number).</li>
              <li><b>Settings</b> (or ⋮) → <b>Linked devices</b> → <b>Link a device</b>.</li>
              <li>Point the phone at this QR code.</li>
            </ol>
          </div>
        ) : status.state === "connecting" ? (
          <div className="space-y-2">
            <p className="flex items-center gap-2 text-sm">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
              Connecting to WhatsApp… (up to a minute)
            </p>
            {status.error && <p className="text-sm text-amber-800">{status.error}</p>}
            <button
              disabled={busy}
              onClick={() => act(wa.logout)}
              className="text-sm text-slate-500 underline hover:text-red-700"
              title="Clears the saved WhatsApp login so you can scan a new QR code"
            >
              Stuck? Start over (link again with a new QR)
            </button>
          </div>
        ) : (
          <div>
            {status.error && <p className="mb-2 text-sm text-slate-600">{status.error}</p>}
            <button
              disabled={busy}
              onClick={() => act(wa.link)}
              className="rounded-xl bg-teal-700 px-5 py-2.5 font-semibold text-white hover:bg-teal-600 disabled:opacity-40"
            >
              Link WhatsApp
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function Connected({ status, onLogout, busy }: { status: WaStatus; onLogout: () => void; busy: boolean }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
        <span className="text-sm">
          Linked{status.me?.name ? ` as ${status.me.name}` : ""} ·{" "}
          {status.mode === "manual" ? `watching ${status.selected ?? 0} chosen chat(s)` : "watching unknown numbers"} ·{" "}
          {status.checked_total ?? 0} message(s) checked
        </span>
        <button disabled={busy} onClick={onLogout} className="ml-auto text-sm text-slate-500 hover:text-red-700">
          Unlink WhatsApp
        </button>
      </div>
      <ChatPicker />
      <Alerts />
    </div>
  );
}

function ChatPicker() {
  const [chats, setChats] = useState<WaChat[]>([]);
  const [policy, setPolicy] = useState<WaPolicy>({ mode: "unknown", include: [], exclude: [] });
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [query, setQuery] = useState("");
  const [number, setNumber] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  const load = useCallback(async () => {
    const res = await wa.chats();
    setChats(res.chats);
    if (!dirtyRef.current) setPolicy({ mode: res.mode, include: res.include, exclude: res.exclude });
  }, []);
  useEffect(() => {
    load().catch(() => {});
    const id = setInterval(() => load().catch(() => {}), 10_000); // new chats and callers appear by themselves
    return () => clearInterval(id);
  }, [load]);

  // What the user sees while editing (before Save): same rules as the bridge.
  const watched = (c: WaChat) =>
    policy.exclude.includes(c.id) ? false
      : policy.include.includes(c.id) ? true
      : policy.mode === "unknown" && !c.saved && !c.isGroup;

  const change = (p: WaPolicy) => {
    setPolicy(p);
    setDirty(true);
    setSaved(false);
  };
  const toggle = (c: WaChat) => {
    const inc = policy.include.filter((x) => x !== c.id);
    const exc = policy.exclude.filter((x) => x !== c.id);
    const auto = policy.mode === "unknown" && !c.saved && !c.isGroup;
    if (watched(c)) change({ ...policy, include: inc, exclude: auto ? [...exc, c.id] : exc });
    else change({ ...policy, include: auto ? inc : [...inc, c.id], exclude: exc });
  };
  const save = async () => {
    await wa.setPolicy(policy);
    setDirty(false);
    setSaved(true);
    await load();
  };
  const addNumber = async () => {
    setAddError(null);
    try {
      await wa.addNumber(number);
      setNumber("");
      setDirty(false);
      await load();
    } catch (e) {
      setAddError(e instanceof ApiError ? e.message : "Could not add this number.");
    }
  };

  const watchedCount = chats.filter(watched).length;
  const shown = useMemo(() => {
    const q = query.toLowerCase();
    const digits = query.replace(/[^\d]/g, "");
    return chats
      // keep rows the user just changed visible, so an untick can be undone
      .filter((c) => showAll || watched(c) || c.calledRecently || policy.exclude.includes(c.id) || policy.include.includes(c.id))
      .filter((c) => !q || c.name.toLowerCase().includes(q) || (digits && c.id.startsWith(digits)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chats, query, showAll, policy]);

  return (
    <div className="space-y-3">
      <div>
        <h3 className="font-semibold">Which chats to watch</h3>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {([
            ["unknown", "Unknown numbers (recommended)", "Every number that isn't saved in your contacts, and unknown callers. New ones are added automatically."],
            ["manual", "Only chats I pick", "Nothing is watched unless you tick it below."],
          ] as const).map(([mode, title, desc]) => (
            <label key={mode} className={`cursor-pointer rounded-xl border p-3 text-sm ${policy.mode === mode ? "border-teal-600 bg-teal-50" : "border-slate-200"}`}>
              <input type="radio" name="wa-mode" className="mr-2 accent-teal-700" checked={policy.mode === mode}
                     onChange={() => change({ ...policy, mode })} />
              <b>{title}</b>
              <p className="mt-1 text-xs text-slate-600">{desc}</p>
            </label>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">Watching <b>{watchedCount}</b> of {chats.length} chats</span>
        <button onClick={() => setShowAll(!showAll)} className="text-sm text-teal-700 hover:underline">
          {showAll ? "Show only watched" : "Show all chats"}
        </button>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search…"
               className="ml-auto w-40 rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />
        <button onClick={save} disabled={!dirty}
                className="rounded-lg bg-teal-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-40">
          {saved && !dirty ? "Saved ✓" : "Save"}
        </button>
      </div>

      {chats.length === 0 ? (
        <p className="text-sm text-slate-500">Loading your chats… (this takes up to a minute right after linking)</p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-slate-500">No unknown numbers yet. They'll appear here as soon as one messages or calls you.</p>
      ) : (
        <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200">
          {shown.map((c) => (
            <li key={c.id}>
              <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50">
                <input type="checkbox" checked={watched(c)} onChange={() => toggle(c)} className="h-4 w-4 accent-teal-700" />
                <span dir="auto" className="flex-1 truncate">{c.name}</span>
                {c.calledRecently && <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">📞 called you</span>}
                {!c.saved && !c.isGroup && <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">not in contacts</span>}
                {c.isGroup && <span className="text-xs text-slate-400">group</span>}
              </label>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">Watch a specific number:</span>
        <input value={number} onChange={(e) => setNumber(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && number.trim() && addNumber()}
               placeholder="+961 70 123 456" className="w-44 rounded-lg border border-slate-300 px-3 py-1" />
        <button onClick={addNumber} disabled={!number.trim()}
                className="rounded-lg border border-slate-300 px-3 py-1 hover:bg-slate-50 disabled:opacity-40">Add</button>
        {addError && <span className="text-red-700">{addError}</span>}
      </div>
      <p className="text-xs text-slate-400">Only watched chats are ever read. Saved contacts (family, friends) stay private unless you tick them.</p>
    </div>
  );
}

function Alerts() {
  const [alerts, setAlerts] = useState<WaAlert[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    const load = () => wa.alerts().then(setAlerts, () => {});
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <div className="mb-2 flex items-center">
        <h3 className="font-semibold">Suspicious messages</h3>
        {alerts.length > 0 && (
          <button onClick={() => wa.clearAlerts().then(() => setAlerts([]))} className="ml-auto text-xs text-slate-500 hover:text-red-700">
            Clear
          </button>
        )}
      </div>
      {alerts.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing suspicious yet. New messages in the watched chats are checked automatically.</p>
      ) : (
        <ul className="space-y-2">
          {alerts.map((a) => (
            <li key={a.id} className="rounded-xl border border-slate-200">
              <button className="flex w-full items-center gap-3 p-3 text-left" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <RiskBadge level={a.evidence.risk_level} />
                <span dir="auto" className="shrink-0 text-sm font-medium">{a.chat_name}</span>
                <span dir="auto" className="min-w-0 flex-1 truncate text-sm text-slate-600">
                  {a.kind === "image" ? "📷 Photo with a QR code" : a.kind.endsWith("call") ? "📞 Called you" : a.text}
                </span>
                <span className="shrink-0 text-xs text-slate-400">{new Date(a.received_at).toLocaleTimeString()}</span>
              </button>
              {open === a.id && (
                <div className="border-t border-slate-100 p-3">
                  <Verdict ev={a.evidence} checked={a.text ? { kind: "text", text: a.text } : null} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-slate-400">Kept in memory only, until Amaan restarts.</p>
    </div>
  );
}
