import { useState } from "react";
import type { AnalyzedItem, EvidenceLabel, RiskLevel, Severity, Signal, SourceResult } from "../types";

// Technical details for one found item (shown under "Show technical details").
// Security: every string from the backend is rendered as plain text by React.
// Links are shown defanged and are never clickable.

export const RISK_STYLE: Record<RiskLevel, string> = {
  Low: "bg-emerald-100 text-emerald-800 border-emerald-300",
  Medium: "bg-amber-100 text-amber-900 border-amber-300",
  High: "bg-red-100 text-red-800 border-red-300",
};

const LABEL_TEXT: Record<EvidenceLabel, string> = {
  automated_indicator: "Automated indicator",
  community_report: "Community report",
  verified: "Verified",
};
const LABEL_STYLE: Record<EvidenceLabel, string> = {
  automated_indicator: "bg-slate-100 text-slate-700",
  community_report: "bg-purple-100 text-purple-800",
  verified: "bg-emerald-100 text-emerald-800",
};
const SEV_DOT: Record<Severity, string> = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-yellow-300",
  info: "bg-sky-400",
  good: "bg-emerald-500",
};
const KIND_TEXT: Record<string, string> = {
  url: "Link", wifi: "Wi-Fi", tel: "Phone call", sms: "SMS", mailto: "E-mail", geo: "Location", text: "Text",
};
const SOURCE_TEXT: Record<string, string> = {
  text: "found in text", html_link: "link target", uri_list: "dropped link", qr: "from QR code",
};

export function RiskBadge({ level, big = false }: { level: RiskLevel; big?: boolean }) {
  return (
    <span className={`inline-block rounded-full border font-bold ${RISK_STYLE[level]} ${big ? "px-4 py-1 text-lg" : "px-2 py-0.5 text-xs"}`}>
      {level} risk
    </span>
  );
}

function SignalRow({ s }: { s: Signal }) {
  return (
    <li className="flex gap-2 py-1.5">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${SEV_DOT[s.severity]}`} title={s.severity} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">{s.title}</span>
          <span className={`rounded px-1.5 text-[11px] font-medium ${LABEL_STYLE[s.label]}`}>{LABEL_TEXT[s.label]}</span>
          <span className="text-[11px] text-slate-400">via {s.source === "urlvet" ? "URL.vet" : s.source === "amaan" ? "Amaan" : s.source}</span>
        </div>
        {s.detail && <p className="text-sm text-slate-600" dir="auto">{s.detail}</p>}
      </div>
    </li>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score < 30 ? "bg-red-500" : score < 65 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="h-2 w-40 overflow-hidden rounded-full bg-slate-200" title={`${score}/100 (higher is safer)`}>
      <div className={`h-full ${color}`} style={{ width: `${Math.max(3, score)}%` }} />
    </div>
  );
}

function Reasons({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div>
      <p className={`text-xs font-semibold uppercase tracking-wide ${tone}`}>{title}</p>
      <ul className="ml-4 list-disc text-sm text-slate-700">
        {items.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
    </div>
  );
}

const VERDICT_CHIP: Record<string, [string, string]> = {
  malicious: ["Flagged", "bg-red-100 text-red-800"],
  suspicious: ["Suspicious", "bg-amber-100 text-amber-900"],
  clean: ["Nothing found", "bg-emerald-100 text-emerald-800"],
  unknown: ["No data", "bg-slate-100 text-slate-600"],
};

function chip(r: SourceResult): [string, string] {
  if (r.status === "ok") return VERDICT_CHIP[r.verdict];
  if (r.status === "not_configured") return ["Not set up", "bg-slate-50 text-slate-400"];
  if (r.status === "rate_limited") return ["Limit reached", "bg-slate-100 text-slate-600"];
  return ["Couldn't check", "bg-slate-100 text-slate-600"];
}

/** Multi-source results, VirusTotal-style: one row per source. */
function Sources({ sources }: { sources: SourceResult[] }) {
  if (!sources.length) return null;
  const checked = sources.filter((r) => r.status === "ok");
  const flagged = checked.filter((r) => r.verdict === "malicious" || r.verdict === "suspicious");
  return (
    <div className="rounded-lg bg-slate-50 p-3">
      <p className="text-sm font-semibold">
        Security sources: {flagged.length} of {checked.length} flagged it
        <span className="ml-2 text-xs font-normal text-slate-500">(each source sees only the link)</span>
      </p>
      <table className="mt-2 w-full text-sm">
        <tbody>
          {sources.map((r) => {
            const [text, cls] = chip(r);
            return (
              <tr key={r.source} className="border-t border-slate-200/70">
                <td className="py-1 pr-3 font-medium">{r.source}</td>
                <td className="py-1 pr-3"><span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>{text}</span></td>
                <td className="py-1 text-xs text-slate-500">{r.detail}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Other sites' own rating of each link. Opened only when the user clicks one. */
export function Lookups({ items }: { items: AnalyzedItem[] }) {
  const links = items.filter((i) => i.lookups?.length).slice(0, 3);
  if (!links.length) return null;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 className="font-semibold">Check it yourself on other sites</h3>
      <p className="mb-2 text-xs text-slate-500">
        Each opens that site's rating of the link in a new tab. The site sees the link (not your message); the link itself is never opened.
      </p>
      {links.map((it) => (
        <div key={it.id} className="mb-2 last:mb-0">
          {links.length > 1 && <p className="mb-1 break-all font-mono text-xs text-slate-600" dir="ltr">{it.display}</p>}
          <ul className="grid gap-1 sm:grid-cols-2">
            {it.lookups!.map((l) => (
              <li key={l.id}>
                <a href={l.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
                  className="block rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm hover:border-teal-400 hover:bg-teal-50">
                  <span className="font-medium text-teal-800">{l.name} ↗</span>
                  <span className="block text-xs text-slate-500">{l.about}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function ItemCard({ item }: { item: AnalyzedItem }) {
  const [open, setOpen] = useState(item.risk_level !== "Low");
  const [copied, setCopied] = useState(false);
  const uv = item.urlvet;
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button className="flex w-full items-start gap-3 p-3 text-left" onClick={() => setOpen(!open)}>
        <RiskBadge level={item.risk_level} />
        <div className="min-w-0 flex-1">
          <p className="break-all font-mono text-sm" dir="ltr">{item.display}</p>
          {item.host && item.host_ascii && item.host !== item.host_ascii && (
            <p className="text-xs text-slate-500" dir="ltr">Shown as {item.host}, real address {item.host_ascii}</p>
          )}
          <p className="text-sm text-slate-600">{item.summary}</p>
        </div>
        <span className="shrink-0 text-xs text-slate-400">
          {KIND_TEXT[item.kind]} · {SOURCE_TEXT[item.source]} {open ? "▴" : "▾"}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 p-3">
          {Object.keys(item.details).length > 0 && (
            <table className="text-sm">
              <tbody>
                {Object.entries(item.details).map(([k, v]) => (
                  <tr key={k}>
                    <td className="pr-3 align-top capitalize text-slate-500">{k}</td>
                    <td className="break-all" dir="auto">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {uv && (
            <div className="rounded-lg bg-slate-50 p-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-semibold">URL.vet</span>
                {uv.mock && (
                  <span className="rounded bg-fuchsia-100 px-1.5 text-[11px] font-bold text-fuchsia-800">MOCK: fake result</span>
                )}
                {uv.status === "ok" ? (
                  <>
                    <span className="text-sm">{uv.verdict ?? "No verdict"}</span>
                    {uv.final_score !== null && <ScoreBar score={uv.final_score} />}
                    {uv.final_score !== null && (
                      <span className="text-xs text-slate-500">
                        score {uv.final_score}/100 · trust {uv.trust_score ?? "?"} · risk {uv.risk_score ?? "?"}
                      </span>
                    )}
                    {uv.incomplete && <span className="text-xs text-amber-700">some checks did not finish</span>}
                  </>
                ) : (
                  <span className="text-sm text-amber-800">{uv.message}</span>
                )}
                {uv.elapsed_ms !== null && <span className="ml-auto text-xs text-slate-400">{(uv.elapsed_ms / 1000).toFixed(1)} s</span>}
              </div>
              {uv.status === "ok" && (
                <div className="mt-2 space-y-2">
                  <Reasons title="Red flags" items={uv.bad_reasons} tone="text-red-700" />
                  <Reasons title="Good signs" items={uv.good_reasons} tone="text-emerald-700" />
                  <Reasons title="Notes" items={uv.neutral_reasons} tone="text-slate-500" />
                  {uv.redirect_chain.length > 1 && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Where it really goes</p>
                      <ol className="ml-4 list-decimal break-all font-mono text-xs text-slate-700" dir="ltr">
                        {uv.redirect_chain.map((u, i) => <li key={i}>{u}</li>)}
                      </ol>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <Sources sources={item.sources ?? []} />

          {item.signals.length > 0 && (
            <ul className="divide-y divide-slate-100">
              {item.signals.map((s, i) => <SignalRow key={i} s={s} />)}
            </ul>
          )}

          {item.kind === "url" && (
            <button
              className="text-xs text-teal-700 hover:underline"
              onClick={() => {
                navigator.clipboard?.writeText(item.display).then(() => setCopied(true), () => {});
              }}
            >
              {copied ? "Copied (defanged)" : "Copy defanged link"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
