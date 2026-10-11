// Mirrors backend/amaan/schemas.py

export type RiskLevel = "Low" | "Medium" | "High";
export type EvidenceLabel = "automated_indicator" | "community_report" | "verified";
export type Severity = "info" | "good" | "low" | "medium" | "high";
export type InputType = "text" | "image" | "camera";
export type ItemKind = "url" | "wifi" | "tel" | "sms" | "mailto" | "geo" | "text";
export type ItemSource = "text" | "html_link" | "uri_list" | "qr";
export type UrlVetStatus = "ok" | "unavailable" | "timeout" | "rate_limited" | "rejected" | "error" | "skipped";

export interface Signal {
  id: string;
  title: string;
  detail: string;
  severity: Severity;
  label: EvidenceLabel;
  source: string;
}

export interface UrlVetResult {
  status: UrlVetStatus;
  message: string;
  verdict: string | null;
  final_score: number | null;
  trust_score: number | null;
  risk_score: number | null;
  bad_reasons: string[];
  good_reasons: string[];
  neutral_reasons: string[];
  final_url: string | null;
  redirect_chain: string[];
  threat_listed: boolean;
  threat_sources: string[];
  incomplete: boolean;
  elapsed_ms: number | null;
  mock: boolean;
}

export interface AnalyzedItem {
  id: number;
  kind: ItemKind;
  source: ItemSource;
  display: string;
  host: string | null;
  host_ascii: string | null;
  details: Record<string, string>;
  urlvet: UrlVetResult | null;
  signals: Signal[];
  risk_level: RiskLevel;
  summary: string;
}

export interface Evidence {
  input_type: InputType;
  analyzed_at: string;
  items: AnalyzedItem[];
  signals: Signal[];
  risk_level: RiskLevel;
  complete: boolean;
  explanation: string;
  warnings: string[];
  stats: Record<string, number | string>;
}

export interface Health {
  status: string;
  version: string;
  urlvet: { reachable: boolean; mock: boolean; base_url: string; latency_ms: number };
  qr_decoders: Record<string, boolean>;
}
