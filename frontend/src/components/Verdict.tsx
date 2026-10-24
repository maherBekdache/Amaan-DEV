import { useState } from "react";
import type { Evidence, RiskLevel, Severity, Signal } from "../types";
import AIOpinionCard from "./AIOpinionCard";
import { LabelChip, SEVERITY_DOT } from "./badges";
import { ItemCard, Lookups } from "./ItemDetails";

// Plain-language result: verdict, what to do, why (with evidence labels),
// and the technical details behind a toggle.

const LOOK: Record<RiskLevel, { icon: string; title: string; advice: string; box: string; pill: string }> = {
  High: {
    icon: "⛔",
    title: "Dangerous",
    advice: "Don't open it, don't scan it, and never share codes, passwords or card details.",
    box: "border-red-300 bg-red-50 text-red-900",
    pill: "bg-red-600",
  },
  Medium: {
    icon: "⚠️",
    title: "Be careful",
    advice: "Check with the sender another way (call them) before you open anything or pay.",
    box: "border-amber-300 bg-amber-50 text-amber-900",
    pill: "bg-amber-500",
  },
  Low: {
    icon: "✅",
    title: "No warning signs found",
    advice: "Looks OK, but stay alert: never share verification codes with anyone.",
    box: "border-emerald-300 bg-emerald-50 text-emerald-900",
    pill: "bg-emerald-600",
  },
};

const ORDER: Severity[] = ["high", "medium", "low", "good", "info"];

function topReasons(ev: Evidence): Signal[] {
  const all = [...ev.signals, ...ev.items.flatMap((i) => i.signals)];
  const seen = new Set<string>();
  const sorted = all
    .filter((s) => s.severity !== "info")
    .sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity))
    .filter((s) => (seen.has(s.title) ? false : (seen.add(s.title), true)));
  const out = sorted.slice(0, 5);
  return out.length ? out : all.filter((s) => s.severity === "info").slice(0, 3);
}

export interface Checked {
  kind: "text" | "image";
  text?: string;
  imageUrl?: string; // blob: URL of the user's own image (never a remote URL)
}

export default function Verdict({ ev, checked, aiAuto = false }: { ev: Evidence; checked: Checked | null; aiAuto?: boolean }) {
  const [details, setDetails] = useState(false);
  const look = LOOK[ev.risk_level];
  const reasons = topReasons(ev);

  return (
    <section className="space-y-4">
      <div className={`rounded-2xl border-2 p-5 ${look.box}`}>
        <div className="flex items-start gap-4">
          <span className="text-4xl leading-none">{look.icon}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-bold">{look.title}</h2>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold text-white ${look.pill}`}>
                {ev.risk_level} risk
              </span>
            </div>
            <p className="mt-1 text-[15px] font-medium">{look.advice}</p>
          </div>
          {checked?.imageUrl && (
            <img src={checked.imageUrl} alt="What you checked" className="h-20 w-20 rounded-lg border border-white object-contain bg-white" />
          )}
        </div>
        {checked?.text && (
          <p dir="auto" className="mt-3 line-clamp-2 rounded-lg bg-white/60 px-3 py-2 text-sm text-slate-700">
            “{checked.text}”
          </p>
        )}
      </div>

      {ev.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          {ev.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
        </div>
      )}

      {reasons.length > 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="mb-2 font-semibold">Why?</h3>
          <ul className="space-y-2.5">
            {reasons.map((s, i) => (
              <li key={i} className="flex gap-3">
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${SEVERITY_DOT[s.severity]}`} />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{s.title}</span>
                    <LabelChip label={s.label} />
                  </div>
                  {s.detail && <p dir="auto" className="text-sm text-slate-600">{s.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-slate-500">{ev.explanation}</p>
      )}

      <Lookups items={ev.items} />

      <AIOpinionCard ev={ev} text={checked?.text} auto={aiAuto} />

      {ev.items.length > 0 && (
        <div>
          <button onClick={() => setDetails(!details)} className="text-sm font-medium text-teal-700 hover:underline">
            {details ? "Hide" : "Show"} technical details ({ev.items.length} item{ev.items.length === 1 ? "" : "s"} found) {details ? "▴" : "▾"}
          </button>
          {details && (
            <div className="mt-2 space-y-2">
              {ev.items.map((it) => <ItemCard key={it.id} item={it} />)}
              <p className="text-xs text-slate-400">
                {Object.entries(ev.stats).map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`).join(" · ")}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
