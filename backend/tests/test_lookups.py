from amaan.lookups import lookup_links
from tests.conftest import urlvet_returns


def test_lookup_addresses_are_encoded():
    links = {x.id: x.href for x in lookup_links("https://omt-gift.com/claim?code=1&x=y", "omt-gift.com")}
    assert links["virustotal"] == "https://www.virustotal.com/gui/search/https%253A%252F%252Fomt-gift.com%252Fclaim%253Fcode%253D1%2526x%253Dy"
    assert links["safebrowsing"] == ("https://transparencyreport.google.com/safe-browsing/search?url="
                                     "https%3A%2F%2Fomt-gift.com%2Fclaim%3Fcode%3D1%26x%3Dy")
    assert links["urlvoid"] == "https://www.urlvoid.com/scan/omt-gift.com/"
    assert all(h.startswith("https://") for h in links.values())


def test_bare_links_get_a_scheme():
    assert lookup_links("omt-gift.com/claim", "omt-gift.com")[0].href.endswith("/http%253A%252F%252Fomt-gift.com%252Fclaim")


def test_host_cannot_break_out_of_the_address():
    links = {x.id: x.href for x in lookup_links("http://a.com", "evil.com/../x?y=1#")}
    assert links["urlvoid"] == "https://www.urlvoid.com/scan/evil.com%2F..%2Fx%3Fy%3D1%23/"


def test_link_items_carry_lookups(client):
    urlvet_returns(client, {})
    ev = client.post("/analyze/text", json={"text": "see xn--mt-zka.com and call +9611234567"}).json()
    url_items = [i for i in ev["items"] if i["kind"] == "url"]
    assert url_items and url_items[0]["lookups"][0]["name"] == "VirusTotal"
    assert "xn--mt-zka.com" in url_items[0]["lookups"][2]["href"]
