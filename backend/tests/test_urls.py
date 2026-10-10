import pytest

from amaan.extract.urls import defang, extract_urls


def hosts(text: str) -> list[str]:
    return [u.host_ascii for u in extract_urls(text).urls]


def test_scheme_url():
    r = extract_urls("Check https://example.com/login?x=1 now")
    assert [u.url for u in r.urls] == ["https://example.com/login?x=1"]


def test_bare_domains_and_shorteners():
    assert hosts("go to omt-lb.xyz or bit.ly/3abcD") == ["omt-lb.xyz", "bit.ly"]
    assert extract_urls("bit.ly/3abcD").urls[0].url == "bit.ly/3abcD"


def test_www_prefix():
    assert hosts("visit www.blombank.com.") == ["www.blombank.com"]


def test_lebanese_second_level_suffix():
    u = extract_urls("touch.com.lb").urls[0]
    assert u.registrable == "touch.com.lb"
    assert u.suffix == "com.lb"


def test_arabic_around_links():
    text = "مرحبا، افتح الرابط https://omt-lb.xyz/claim، وبعدين ابعتلي الكود"
    assert extract_urls(text).urls[0].url == "https://omt-lb.xyz/claim"


def test_arabic_glued_to_bare_domain():
    assert hosts("زوروا الموقعexample.comهلق") == ["example.com"]


def test_arabic_question_mark_and_comma():
    assert hosts("شفت whish-money.net؟") == ["whish-money.net"]
    assert hosts("الرابط: paypa1.com،") == ["paypa1.com"]


def test_arabizi_message():
    text = "kifak! 3andak jeyze, eftah hal link: bit.ly/xyz12 w 7ot el code yalla"
    assert hosts(text) == ["bit.ly"]


def test_trailing_punctuation_and_parentheses():
    assert extract_urls("(see https://example.com/a)").urls[0].url == "https://example.com/a"
    u = extract_urls("https://en.wikipedia.org/wiki/Foo_(bar)").urls[0]
    assert u.url.endswith("Foo_(bar)")


def test_punycode_both_ways():
    u = extract_urls("xn--80ak6aa92e.com").urls[0]
    assert u.host == "аррӏе.com"  # Cyrillic lookalike of apple.com
    u2 = extract_urls("аррӏе.com/login").urls[0]
    assert u2.host_ascii == "xn--80ak6aa92e.com"


def test_cyrillic_homograph_bare_domain():
    u = extract_urls("pay here: pаypal.com").urls[0]  # Cyrillic а
    assert u.host_ascii.startswith("xn--")


def test_arabic_idn_with_scheme():
    u = extract_urls("زوروا https://موقع.مصر/ اليوم").urls[0]
    assert u.host_ascii.startswith("xn--")


def test_defanged_input():
    r = extract_urls("bad: hxxps://evil[.]com/x")
    assert r.urls[0].url == "https://evil.com/x"
    assert r.flags.defanged


def test_zero_width_and_bidi_flags():
    r = extract_urls("open exa​mple.com")
    assert hosts("open exa​mple.com") == ["example.com"]
    assert r.flags.zero_width_in_link
    assert extract_urls("‮example.com").flags.bidi_override


def test_fullwidth_dot_and_letters():
    r = extract_urls("ｅｘａｍｐｌｅ。com")
    assert [u.host_ascii for u in r.urls] == ["example.com"]
    assert r.flags.fullwidth


def test_not_urls():
    assert hosts("the price is 3.5 million, v1.2.3 node.js file.txt e.g. i.e.") == []


def test_email_is_not_a_url():
    assert hosts("mail john.doe@example.com") == []


def test_ip_with_path_and_userinfo():
    u = extract_urls("http://paypal.com@192.168.1.5/login").urls[0]
    assert u.is_ip and u.has_userinfo
    assert hosts("router 192.168.1.1/admin") == ["192.168.1.1"]
    assert hosts("version 10.0.0.1") == []  # bare IP without path is ignored


def test_port():
    u = extract_urls("http://example.com:8443/x").urls[0]
    assert u.port == 8443


def test_dedup_and_limit():
    r = extract_urls("example.com https://example.com example.com/", limit=5)
    assert len(r.urls) == 1
    many = " ".join(f"site{i}.com" for i in range(12))
    r2 = extract_urls(many, limit=10)
    assert len(r2.urls) == 10 and r2.truncated


def test_zip_tld_is_a_domain():
    assert hosts("invoice.zip") == ["invoice.zip"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://evil.com/a.b", "hxxps://evil[.]com/a.b"),
        ("bit.ly/x", "bit[.]ly/x"),
        ("http://1.2.3.4:80/", "hxxp://1[.]2[.]3[.]4:80/"),
    ],
)
def test_defang(value, expected):
    assert defang(value) == expected
