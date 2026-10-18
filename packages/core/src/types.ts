// Mirrors backend/amaan/schemas.py (the parts used on the device).
export type RiskLevel = "Low" | "Medium" | "High";
export type Severity = "info" | "good" | "low" | "medium" | "high";
export type EvidenceLabel = "automated_indicator" | "community_report" | "verified";
export type ItemKind = "url" | "wifi" | "tel" | "sms" | "mailto" | "geo" | "text";

export interface Signal {
  id: string;
  title: string;
  detail: string;
  severity: Severity;
  label: EvidenceLabel;
  source: string;
}

export interface Item {
  kind: ItemKind;
  source: "text" | "qr";
  display: string; // defanged
  url?: string; // for links: what to send to the server
  host?: string;
  hostAscii?: string;
  details: Record<string, string>;
  signals: Signal[];
  riskLevel: RiskLevel;
  checked: boolean; // checked by the server (sandbox + sources)
}

export interface Result {
  items: Item[];
  signals: Signal[]; // about the message as a whole
  riskLevel: RiskLevel;
  complete: boolean;
}

export const sig = (id: string, title: string, detail: string, severity: Severity,
                    label: EvidenceLabel = "automated_indicator", source = "amaan"): Signal =>
  ({ id, title, detail, severity, label, source });
