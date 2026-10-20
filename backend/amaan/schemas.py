"""The common Evidence schema returned by every /analyze endpoint.

Design rule: a verdict is never just a score. Every risk level is backed by a
list of Signals, and each Signal states where it came from and what kind of
evidence it is (automated indicator vs. community report vs. verified).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from amaan.lookups import Lookup
from amaan.reputation.base import SourceResult


class RiskLevel(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"


class EvidenceLabel(str, Enum):
    # Produced by an algorithm or heuristic (URL.vet checks, our local rules).
    automated_indicator = "automated_indicator"
    # Comes from people reporting the link (e.g. PhishTank via URL.vet).
    community_report = "community_report"
    # Confirmed against a curated, trusted source (e.g. the official-domain list).
    verified = "verified"


class Severity(str, Enum):
    info = "info"  # context only, does not move the risk level
    good = "good"  # lowers concern
    low = "low"
    medium = "medium"
    high = "high"


class Signal(BaseModel):
    id: str = Field(description="Stable machine id, e.g. 'punycode_host'")
    title: str
    detail: str = ""
    severity: Severity
    label: EvidenceLabel
    source: str = Field(description="'amaan' for our local rules, 'urlvet' for URL.vet")


class InputType(str, Enum):
    text = "text"
    image = "image"
    camera = "camera"


class ItemKind(str, Enum):
    url = "url"
    wifi = "wifi"
    tel = "tel"
    sms = "sms"
    mailto = "mailto"
    geo = "geo"
    text = "text"


class ItemSource(str, Enum):
    text = "text"  # found in pasted / dropped plain text
    html_link = "html_link"  # an <a href> in dropped HTML
    uri_list = "uri_list"  # a dropped link (text/uri-list)
    qr = "qr"  # decoded from a QR code


class UrlVetStatus(str, Enum):
    ok = "ok"
    unavailable = "unavailable"  # connection refused / service down
    timeout = "timeout"
    rate_limited = "rate_limited"
    rejected = "rejected"  # URL.vet answered 400/422 for this URL
    error = "error"
    skipped = "skipped"  # not sent (limit reached, or not a URL)


class UrlVetResult(BaseModel):
    status: UrlVetStatus
    message: str = ""
    verdict: str | None = None  # Safe / Suspicious / Risky
    final_score: int | None = None  # 0-100, higher is safer
    trust_score: int | None = None
    risk_score: int | None = None
    bad_reasons: list[str] = []
    good_reasons: list[str] = []
    neutral_reasons: list[str] = []
    final_url: str | None = None  # where a shortener / redirect leads (defanged)
    redirect_chain: list[str] = []  # defanged
    threat_listed: bool = False
    threat_sources: list[str] = []
    incomplete: bool = False
    elapsed_ms: int | None = None
    mock: bool = False  # answered by devtools/mock_urlvet.py, not the real URL.vet


class AnalyzedItem(BaseModel):
    id: int
    kind: ItemKind
    source: ItemSource
    display: str = Field(description="Defanged, safe-to-show form, e.g. hxxps://example[.]com")
    host: str | None = None  # Unicode form of the host
    host_ascii: str | None = None  # punycode (xn--) form of the host
    details: dict[str, str] = {}  # payload fields, e.g. Wi-Fi SSID, phone number
    urlvet: UrlVetResult | None = None
    sources: list[SourceResult] = Field(default=[], description="Every reputation source's answer (multi-source check)")
    signals: list[Signal] = []
    risk_level: RiskLevel
    summary: str
    lookups: list[Lookup] = Field(default=[], description="Links: look this link up yourself on other sites")


class Evidence(BaseModel):
    input_type: InputType
    analyzed_at: datetime
    items: list[AnalyzedItem]
    signals: list[Signal] = Field(default=[], description="Signals about the input as a whole")
    risk_level: RiskLevel
    complete: bool = Field(description="False when some check could not run (e.g. URL.vet down)")
    explanation: str
    warnings: list[str] = []
    stats: dict[str, int | float | str] = {}


class TextRequest(BaseModel):
    text: str = ""
    html: str | None = Field(default=None, description="Dropped text/html; parsed, never rendered")
    uri_list: str | None = Field(default=None, description="Dropped text/uri-list")


class HealthResponse(BaseModel):
    status: str
    version: str
    urlvet: dict[str, object]
    qr_decoders: dict[str, bool]
    ai: dict[str, object] = {}
    lookyloo: dict[str, object] = {}


class ExplainRequest(BaseModel):
    evidence: "Evidence"
    text: str | None = Field(default=None, max_length=5000, description="The message, for context (optional)")
    open_page: bool = Field(default=True, description="Let Lookyloo open the first link in its sandbox first")


class ImportFinding(BaseModel):
    index: int
    date: str
    time: str
    sender: str
    text: str = Field(description="The message (truncated); kept in memory only for this response")
    attachment: str | None = None
    evidence: Evidence


class ImportReport(BaseModel):
    title: str
    risk_level: RiskLevel
    messages_total: int
    messages_checked: int
    links_found: int
    links_checked: int
    images_checked: int
    findings: list[ImportFinding]
    warnings: list[str] = []
    stats: dict[str, int | float | str] = {}


class WhatsAppAlert(BaseModel):
    """A flagged message from a chat the user chose to watch. Kept in RAM only (last 50)."""

    id: int
    received_at: datetime
    chat_name: str
    sender: str
    kind: str
    text: str
    evidence: Evidence


class LinkRequest(BaseModel):
    """Hybrid mode (mobile app): only links are sent, never the message or image."""

    urls: list[str] = Field(max_length=10)
