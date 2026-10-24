import os

os.environ.setdefault("AMAAN_FEEDS_ENABLED", "0")  # no list downloads during tests

import io

import httpx
import pytest
import qrcode
import respx
from fastapi.testclient import TestClient
from PIL import Image

from amaan.config import get_settings
from amaan.main import app


def make_qr(data: str, box_size: int = 8, border: int = 4) -> Image.Image:
    qr = qrcode.QRCode(box_size=box_size, border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def qr_png():
    def _make(data: str, fmt: str = "PNG", **kw) -> bytes:
        return to_bytes(make_qr(data, **kw), fmt)

    return _make


@pytest.fixture
def multi_qr_png():
    def _make(*payloads: str) -> bytes:
        imgs = [make_qr(p) for p in payloads]
        w = sum(i.width for i in imgs) + 40 * (len(imgs) + 1)
        h = max(i.height for i in imgs) + 80
        canvas = Image.new("RGB", (w, h), "white")
        x = 40
        for i in imgs:
            canvas.paste(i, (x, 40))
            x += i.width + 40
        return to_bytes(canvas)

    return _make


# --- API client with URL.vet mocked (used by test_api.py and test_lookups.py) ---------------

URLVET = get_settings().urlvet_base_url


def report(verdict: str, score: int, listed: bool = False) -> dict:
    return {"threat_feeds": {"listed": listed, "sources": ["PhishTank"] if listed else []},
            "result": {"verdict": verdict, "final_score": score, "trust_score": score, "risk_score": 100 - score,
                       "reasons": {"bad_reasons": ["New domain."] if verdict != "Safe" else None,
                                   "good_reasons": ["Old domain."] if verdict == "Safe" else None}}}


@pytest.fixture
def client():
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        with TestClient(app) as c:
            c.mock = mock
            yield c


def urlvet_returns(client, mapping: dict[str, dict]):
    def handler(request: httpx.Request):
        target = request.url.params["url"]
        for key, body in mapping.items():
            if key in target:
                return httpx.Response(200, json=body)
        return httpx.Response(200, json=report("Safe", 90))

    client.mock.get(f"{URLVET}/api/v1/analyze").mock(side_effect=handler)
