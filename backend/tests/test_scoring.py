from amaan.extract.payloads import classify_payload
from amaan.extract.urls import extract_urls
from amaan.schemas import EvidenceLabel, ItemKind, RiskLevel, Severity, UrlVetResult, UrlVetStatus
from amaan.scoring import aggregate
from amaan.scoring.local_rules import link_text_mismatch, payload_signals, url_signals
from amaan.scoring.text_cues import text_cue_signals


def ids(text: str) -> set[str]:
    return {s.id for s in url_signals(extract_urls(text).urls[0])}


def test_official_domain_is_verified():
    sigs = url_signals(extract_urls("https://www.omt.com.lb/").urls[0])
    official = [s for s in sigs if s.id == "official_domain"]
    assert official and official[0].label is EvidenceLabel.verified


def test_lookalike_digit_swap():
    assert "lookalike_domain" in ids("paypa1.com")
    assert "lookalike_domain" in ids("0mt.com.lb")


def test_cyrillic_homograph():
    s = ids("pаypal.com")  # Cyrillic а
    assert "mixed_script" in s and "lookalike_domain" in s


def test_brand_in_domain():
    assert "brand_in_domain" in ids("omt-lebanon-gift.xyz")
    assert "brand_in_domain" in ids("whishmoney-lb.com")
    assert "brand_in_domain" not in ids("example.com")


def test_structure_signals():
    assert "userinfo_trick" in ids("http://blombank.com@evil-login.net/login")
    assert "ip_host" in ids("http://10.1.2.3/login")
    assert "shortener" in ids("bit.ly/abc")
    assert "file_like_tld" in ids("invoice.zip")
    assert "no_https" in ids("http://example.com")
    assert "unusual_port" in ids("https://example.com:8443")


def test_link_text_mismatch():
    assert link_text_mismatch("evil-login.net", "www.blombank.com") is not None
    assert link_text_mismatch("blombank.com", "blombank.com") is None
    assert link_text_mismatch("evil-login.net", "Click here") is None


def test_payload_signals():
    assert payload_signals(classify_payload("WIFI:S:Free;T:nopass;;"))[0].severity is Severity.medium
    assert payload_signals(classify_payload("bitcoin:bc1q?amount=1"))[0].severity is Severity.high
    assert payload_signals(classify_payload("SMSTO:1199:YES"))[0].severity is Severity.medium


def test_text_cues_arabic_arabizi_english():
    ar = {s.id for s in text_cue_signals("مبروك ربحت جائزة! ابعتلي الكود يلي وصلك")}
    assert {"cue_prize", "cue_asks_for_code"} <= ar
    az = {s.id for s in text_cue_signals("mabrouk rbe7t jeyze, ab3atli el code bas yeslak")}
    assert {"cue_prize", "cue_asks_for_code"} <= az
    en = text_cue_signals("URGENT: your account will be suspended. Send me the code.")
    assert {s.id for s in en} >= {"cue_urgency_threat", "cue_asks_for_code"}
    assert all(s.severity is Severity.medium for s in en)


def test_text_cues_single_is_low_and_clean_is_empty():
    assert [s.severity for s in text_cue_signals("Your parcel is on its way")] == [Severity.low]
    assert text_cue_signals("ahla w sahla, kifak? see you tomorrow") == []


def test_unchecked_link_is_never_low():
    down = UrlVetResult(status=UrlVetStatus.unavailable)
    assert aggregate.item_level(ItemKind.url, [], down) is RiskLevel.medium


def test_unchecked_official_link_can_be_low():
    sigs = url_signals(extract_urls("https://omt.com.lb").urls[0])
    down = UrlVetResult(status=UrlVetStatus.unavailable)
    assert aggregate.item_level(ItemKind.url, sigs, down) is RiskLevel.low


def test_urlvet_verdict_mapping_and_community_label():
    r = UrlVetResult(status=UrlVetStatus.ok, verdict="Risky", final_score=5, threat_listed=True,
                     threat_sources=["PhishTank"])
    sigs = aggregate.urlvet_signals(r)
    assert any(s.label is EvidenceLabel.community_report for s in sigs)
    assert aggregate.item_level(ItemKind.url, sigs, r) is RiskLevel.high
    safe = UrlVetResult(status=UrlVetStatus.ok, verdict="Safe", final_score=90)
    assert aggregate.item_level(ItemKind.url, aggregate.urlvet_signals(safe), safe) is RiskLevel.low


def test_escalation_link_plus_scam_script():
    from amaan.schemas import AnalyzedItem, ItemSource

    u = extract_urls("omt-gift.xyz").urls[0]
    item = AnalyzedItem(id=1, kind=ItemKind.url, source=ItemSource.text, display="x", signals=url_signals(u),
                        risk_level=RiskLevel.medium, summary="")
    cues = text_cue_signals("mabrouk rbe7t jeyze, ab3atli el code")
    assert aggregate.overall_level([item], cues) is RiskLevel.high
    assert aggregate.overall_level([item], []) is RiskLevel.medium


def test_no_escalation_for_merely_unchecked_link():
    from amaan.schemas import AnalyzedItem, ItemSource

    item = AnalyzedItem(id=1, kind=ItemKind.url, source=ItemSource.text, display="x", signals=[],
                        risk_level=RiskLevel.medium, summary="")
    cues = text_cue_signals("mabrouk rbe7t jeyze, ab3atli el code")
    assert aggregate.overall_level([item], cues) is RiskLevel.medium
