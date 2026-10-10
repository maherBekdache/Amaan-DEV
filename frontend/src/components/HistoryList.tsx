import type { HistoryEntry } from "../lib/history";
import { RiskBadge } from "./ResultPanel";

interface Props {
  entries: HistoryEntry[];
  onClear: () => void;
}

const INPUT_TEXT = { text: "Text", image: "Image", camera: "Camera" } as const;

export default function HistoryList({ entries, onClear }: Props) {
  return (
    <aside className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-center">
        <h2 className="font-semibold">History</h2>
        {entries.length > 0 && (
          <button onClick={onClear} className="ml-auto text-xs text-slate-500 hover:text-red-700">
            Clear history
          </button>
        )}
      </div>
      <p className="mb-2 text-xs text-slate-400">Saved only in this browser. No message text or full links are kept.</p>
      {entries.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing checked yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {entries.map((e) => (
            <li key={e.id} className="flex items-start gap-2 py-2">
              <RiskBadge level={e.risk} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs" dir="ltr" title={e.hosts.join(", ")}>
                  {e.hosts.length ? e.hosts.join(", ") : "no links found"}
                </p>
                <p className="text-[11px] text-slate-400">
                  {INPUT_TEXT[e.inputType]} · {e.itemCount} item{e.itemCount === 1 ? "" : "s"} ·{" "}
                  {new Date(e.at).toLocaleString()}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
