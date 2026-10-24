import type { EvidenceLabel, RiskLevel, Severity } from "../types";

// Small pieces shared by every result view. The label names follow the project
// rule: "Automated check" / "Reported by others" / "Verified" stay distinct.

const RISK_STYLE: Record<RiskLevel, string> = {
  Low: "bg-emerald-100 text-emerald-800 border-emerald-300",
  Medium: "bg-amber-100 text-amber-900 border-amber-300",
  High: "bg-red-100 text-red-800 border-red-300",
};

const LABEL: Record<EvidenceLabel, [string, string]> = {
  automated_indicator: ["Automated check", "bg-slate-200 text-slate-700"],
  community_report: ["Reported by others", "bg-purple-200 text-purple-900"],
  verified: ["Verified", "bg-emerald-200 text-emerald-900"],
};

export const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-red-500", medium: "bg-amber-500", low: "bg-yellow-400", good: "bg-emerald-500", info: "bg-sky-400",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-bold ${RISK_STYLE[level]}`}>
      {level} risk
    </span>
  );
}

export function LabelChip({ label }: { label: EvidenceLabel }) {
  const [text, cls] = LABEL[label];
  return <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>{text}</span>;
}
