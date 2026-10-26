// AI summary from the paired computer's model. The phone sends Amaan's findings
// (signals, defanged links, the computer's own link checks), never the message
// text or the picture: the computer's /gateway/ai/explain also ignores any text.
import type { Item, Result } from "@amaan/core";
import type { Checked } from "./check";
import { explain, type AIOpinion, type Pairing } from "./server";

const KINDS = new Set(["url", "wifi", "tel", "sms", "mailto", "geo", "text"]);

/** The phone's result in the backend's Evidence shape (only what the summary needs). */
export function toEvidence(r: Result & Partial<Pick<Checked, "server" | "warnings">>, inputType: "text" | "image") {
  const server = new Map((r.server ?? []).filter((s) => s.host_ascii).map((s) => [s.host_ascii!, s]));
  const item = (it: Item, id: number) => {
    const s = it.hostAscii ? server.get(it.hostAscii) : undefined;
    return {
      id, kind: KINDS.has(it.kind) ? it.kind : "text", source: it.source, display: it.display,
      host: it.host ?? null, host_ascii: it.hostAscii ?? null, details: it.details, signals: it.signals,
      risk_level: it.riskLevel, summary: "", urlvet: s?.urlvet ?? null, sources: s?.sources ?? [],
    };
  };
  return {
    input_type: inputType, analyzed_at: new Date().toISOString(), items: r.items.map((it, i) => item(it, i + 1)),
    signals: r.signals, risk_level: r.riskLevel, complete: r.complete, explanation: "", warnings: r.warnings ?? [], stats: {},
  };
}

export function explainResult(p: Pairing, r: Checked, inputType: "text" | "image"): Promise<AIOpinion> {
  return explain(p, toEvidence(r, inputType));
}
