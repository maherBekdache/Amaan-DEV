"""Guards the demo: every built-in example (frontend/src/examples.json) must keep producing the
signals and risk level the demo script relies on (URL.vet switched off, so
only Amaan's own rules count)."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from amaan.config import get_settings
from amaan.main import app

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = json.loads((ROOT / "frontend" / "src" / "examples.json").read_text(encoding="utf-8"))
IMAGES = ROOT / "frontend" / "public" / "examples"
URLVET = get_settings().urlvet_base_url


@pytest.fixture(scope="module")
def client():
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{URLVET}/api/v1/analyze").mock(side_effect=httpx.ConnectError("off"))
        with TestClient(app) as c:
            yield c


def all_signal_ids(ev: dict) -> set[str]:
    return {s["id"] for s in ev["signals"]} | {s["id"] for i in ev["items"] for s in i["signals"]}


@pytest.mark.parametrize("sample", SAMPLES["text"], ids=lambda s: s["id"])
def test_text_samples(client, sample):
    ev = client.post("/analyze/text", json={"text": sample["text"]}).json()
    assert set(sample["expect_signals"]) <= all_signal_ids(ev)
    assert ev["risk_level"] == sample["expect_risk"]


@pytest.mark.parametrize("sample", SAMPLES["qr"], ids=lambda s: s["file"])
def test_qr_samples(client, sample):
    data = (IMAGES / sample["file"]).read_bytes()
    ev = client.post("/analyze/image", files={"file": (sample["file"], data, "image/png")}).json()
    assert ev["stats"]["qr_codes"] == 1
    assert set(sample["expect_signals"]) <= all_signal_ids(ev)
    assert ev["risk_level"] == sample["expect_risk"]


def test_multi_qr_sample(client):
    s = SAMPLES["qr_multi"]
    ev = client.post("/analyze/image", files={"file": (s["file"], (IMAGES / s["file"]).read_bytes(), "image/png")}).json()
    assert ev["stats"]["qr_codes"] == len(s["payloads"])
    assert ev["risk_level"] == s["expect_risk"]


def test_photo_sample(client):
    s = SAMPLES["qr_photo"]
    ev = client.post("/analyze/image", files={"file": (s["file"], (IMAGES / s["file"]).read_bytes(), "image/jpeg")}).json()
    assert ev["stats"]["qr_codes"] == 1
    assert set(s["expect_signals"]) <= all_signal_ids(ev)
