import io

import pytest
from PIL import Image

from amaan.extract.payloads import classify_payload
from amaan.extract.qr import ImageRejected, available_decoders, decode_qr_codes
from amaan.schemas import ItemKind
from tests.conftest import make_qr, to_bytes


def texts(data: bytes, **kw) -> set[str]:
    return {c.text for c in decode_qr_codes(data, **kw).codes}


def test_decoders_available():
    d = available_decoders()
    assert d["opencv"]


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_single_qr_formats(qr_png, fmt):
    assert texts(qr_png("https://omt-lb.xyz/claim", fmt=fmt)) == {"https://omt-lb.xyz/claim"}


def test_multiple_qr_codes(multi_qr_png):
    data = multi_qr_png("https://a.example.com", "WIFI:S:Cafe;T:WPA;P:secret;;", "tel:+96170123456")
    assert texts(data) == {"https://a.example.com", "WIFI:S:Cafe;T:WPA;P:secret;;", "tel:+96170123456"}


def test_arabic_payload(qr_png):
    assert texts(qr_png("مرحبا https://example.com")) == {"مرحبا https://example.com"}


def test_small_qr_in_large_photo():
    canvas = Image.new("RGB", (2400, 1800), (200, 200, 200))
    canvas.paste(make_qr("https://bit.ly/abc", box_size=4), (1700, 1200))
    assert texts(to_bytes(canvas, "JPEG")) == {"https://bit.ly/abc"}


def test_transparent_png():
    img = make_qr("https://example.com").convert("RGBA")
    px = img.load()
    for x in range(img.width):
        for y in range(img.height):
            if px[x, y][:3] == (255, 255, 255):
                px[x, y] = (0, 0, 0, 0)
    assert texts(to_bytes(img)) == {"https://example.com"}


def test_inverted_qr():
    from PIL import ImageOps

    img = ImageOps.invert(make_qr("https://example.com/inv"))
    assert texts(to_bytes(img)) == {"https://example.com/inv"}


def test_no_qr():
    img = Image.new("RGB", (400, 300), "white")
    assert texts(to_bytes(img)) == set()


def test_rejects_non_image():
    with pytest.raises(ImageRejected):
        decode_qr_codes(b"this is not an image")


def test_rejects_empty():
    with pytest.raises(ImageRejected):
        decode_qr_codes(b"")


def test_rejects_gif():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="GIF")
    with pytest.raises(ImageRejected, match="Unsupported"):
        decode_qr_codes(buf.getvalue())


def test_rejects_huge_image():
    # 5000x5000 = 25 MP is over a 10 MP limit; PNG of a blank image stays small.
    data = to_bytes(Image.new("L", (5000, 5000), 255))
    with pytest.raises(ImageRejected, match="too large"):
        decode_qr_codes(data, max_pixels=10_000_000)


def test_truncated_image(qr_png):
    data = qr_png("https://example.com", fmt="JPEG")
    with pytest.raises(ImageRejected):
        decode_qr_codes(data[: len(data) // 3])


# --- payload classification ----------------------------------------------------


def test_classify_wifi_hides_password():
    p = classify_payload(r"WIFI:T:WPA;S:My\;Cafe;P:pa\:ss;H:true;;")
    assert p.kind is ItemKind.wifi
    assert p.details == {"ssid": "My;Cafe", "security": "WPA", "hidden": "yes", "password": "included (hidden)"}


def test_classify_open_wifi():
    p = classify_payload("WIFI:S:Free;T:nopass;;")
    assert p.details["security"] == "open (no password)"


@pytest.mark.parametrize(
    "raw,kind,details",
    [
        ("tel:+96170123456", ItemKind.tel, {"number": "+96170123456"}),
        ("SMSTO:1234:SUB ON", ItemKind.sms, {"number": "1234", "message": "SUB ON"}),
        ("sms:+961123?body=hello%20there", ItemKind.sms, {"number": "+961123", "message": "hello there"}),
        ("mailto:a@b.com?subject=Hi", ItemKind.mailto, {"address": "a@b.com", "subject": "Hi"}),
        ("geo:33.89,35.50", ItemKind.geo, {"location": "33.89,35.50"}),
        ("https://x.com", ItemKind.url, {}),
        ("just some words", ItemKind.text, {}),
    ],
)
def test_classify(raw, kind, details):
    p = classify_payload(raw)
    assert p.kind is kind
    assert p.details == details


def test_classify_crypto():
    p = classify_payload("bitcoin:bc1qxyz?amount=0.5")
    assert p.scheme == "bitcoin"
    assert p.details["amount"] == "0.5"
