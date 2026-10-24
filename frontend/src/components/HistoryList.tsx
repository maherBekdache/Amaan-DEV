import type { HistoryEntry } from "../lib/history";
import { RiskBadge } from "./badges";

// Stored only in this browser: verdict + defanged site names, never message text.
export default function HistoryList({ entries, onClear }: { entries: HistoryEntry[]; onClear: () => void }) {
  if (entries.length === 0) return null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-1 flex items-center">
        <h2 className="font-semibold">Recent checks</h2>
        <span className="ml-2 text-xs text-slate-400">saved only on this computer, without message text</span>
        <button onClick={onClear} className="ml-auto text-xs text-slate-500 hover:text-red-700">Clear</button>
      </div>
      <ul className="divide-y divide-slate-100">
        {entries.slice(0, 8).map((e) => (
          <li key={e.id} className="flex items-center gap-3 py-1.5 text-sm">
            <RiskBadge level={e.risk} />
            <span className="min-w-0 flex-1 truncate font-mono text-xs" dir="ltr">
              {e.hosts.length ? e.hosts.join(", ") : "nothing found"}
            </span>
            <span className="shrink-0 text-xs text-slate-400">{new Date(e.at).toLocaleTimeString()}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
