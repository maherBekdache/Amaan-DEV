import { useEffect, useState } from "react";
import { ApiError, explain } from "../lib/api";
import type { AIOpinion, Evidence } from "../types";

const RISK: Record<string, [string, string]> = {
  high: ["thinks it's dangerous", "bg-red-100 text-red-800"],
  medium: ["thinks you should be careful", "bg-amber-100 text-amber-900"],
  low: ["sees no clear scam", "bg-emerald-100 text-emerald-800"],
};

/** Local AI second opinion. Advisory only: the verdict above comes from evidence. */
export default function AIOpinionCard({ ev, text, auto }: { ev: Evidence; text?: string; auto: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [op, setOp] = useState<AIOpinion | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setState("loading");
    setError(null);
    try {
      setOp(await explain(ev, text));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The AI opinion failed.");
    } finally {
      setState("done");
    }
  };

  useEffect(() => {
    setOp(null);
    setState("idle");
    if (auto) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ev, auto]);

  return (
    <div className="rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg">🤖</span>
        <h3 className="font-semibold">AI second opinion</h3>
        {op?.available && op.risk && (
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${RISK[op.risk][1]}`}>AI {RISK[op.risk][0]}</span>
        )}
        <span className="ml-auto text-xs text-slate-500">
          {op?.available ? `${op.model} · on this computer · ${(op.elapsed_ms / 1000).toFixed(1)} s` : "runs on this computer"}
        </span>
      </div>

      {state === "idle" && (
        <button onClick={run} className="mt-2 rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">
          Ask the AI
        </button>
      )}
      {state === "loading" && (
        <p className="mt-2 flex items-center gap-2 text-sm text-slate-600">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          Thinking… (opening the link in a sandbox first if Lookyloo is running; can take up to a minute)
        </p>
      )}
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      {op && !op.available && <p className="mt-2 text-sm text-slate-600">{op.message}</p>}
      {op?.available && (
        <div className="mt-2 space-y-2 text-sm">
          <p>{op.reasoning}</p>
          {op.red_flags.length > 0 && (
            <ul className="ml-5 list-disc text-slate-700">{op.red_flags.map((f, i) => <li key={i}>{f}</li>)}</ul>
          )}
          {op.advice && <p className="font-medium">{op.advice}</p>}
          {op.page_note && <p className="text-xs text-slate-500">{op.page_checked ? "🔍 " : ""}{op.page_note}</p>}
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-400">
        An AI can be wrong. The verdict above is based on the evidence listed; this is only a second opinion.
      </p>
    </div>
  );
}
