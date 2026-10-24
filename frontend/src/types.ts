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

export interface SourceResult {
  source: string;
  kind: string;
  status: "ok" | "not_configured" | "timeout" | "rate_limited" | "error";
  verdict: "malicious" | "suspicious" | "clean" | "unknown";
  detail: string;
  community: boolean;
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
  sources: SourceResult[];
  signals: Signal[];
  risk_level: RiskLevel;
  summary: string;
  lookups?: Lookup[];
}

export interface Lookup {
  id: string;
  name: string;
  about: string;
  href: string;
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
  ai?: { available: boolean; model: string | null; provider: string | null };
  lookyloo?: { enabled: boolean; reachable: boolean };
}

export interface Pairing {
  enabled: boolean;
  server?: string;
  token?: string;
  pair_uri?: string;
  message?: string;
}

export interface AIOpinion {
  available: boolean;
  provider: string;
  model: string;
  risk: "low" | "medium" | "high" | null;
  reasoning: string;
  red_flags: string[];
  advice: string;
  page_checked: boolean;
  page_note: string;
  elapsed_ms: number;
  message: string;
}

export interface ImportFinding {
  index: number;
  date: string;
  time: string;
  sender: string;
  text: string;
  attachment: string | null;
  evidence: Evidence;
}

export interface ImportReport {
  title: string;
  risk_level: RiskLevel;
  messages_total: number;
  messages_checked: number;
  links_found: number;
  links_checked: number;
  images_checked: number;
  findings: ImportFinding[];
  warnings: string[];
}

export type WaState = "idle" | "connecting" | "qr" | "connected";

export interface WaStatus {
  enabled: boolean;
  state?: WaState;
  qr?: string | null; // data: URL generated locally by the bridge
  me?: { id: string | null; name: string | null } | null;
  error?: string | null;
  selected?: number;
  mode?: "unknown" | "manual";
  checked_total?: number;
}

export interface WaChat {
  id: string;
  name: string;
  isGroup: boolean;
  saved: boolean; // in the phone's contacts
  calledRecently: boolean;
  auto: boolean; // watched automatically because it's an unknown number
  selected: boolean; // watched right now
}

export interface WaPolicy {
  mode: "unknown" | "manual";
  include: string[];
  exclude: string[];
}

export interface WaAlert {
  id: number;
  received_at: string;
  chat_name: string;
  sender: string;
  kind: string;
  text: string;
  evidence: Evidence;
}
