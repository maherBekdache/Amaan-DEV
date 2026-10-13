import io
import zipfile

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from amaan.api import whatsapp as wa_api
from amaan.config import get_settings
from amaan.importers.whatsapp_export import ExportRejected, load_export, parse_text
from amaan.main import app
from tests.conftest import make_qr, to_bytes

S = get_settings()
URLVET = S.urlvet_base_url
BRIDGE = S.whatsapp_bridge_url

ANDROID = """12/10/2026, 14:05 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.
12/10/2026, 14:05 - Ali: kifak?
12/10/2026, 14:06 - Unknown: Mabrouk! rbe7t jeyze men OMT
ekbos hon omt-gift.example.com/claim w ab3atli el code
12/10/2026, 14:07 - Ali: IMG-20261012-WA0001.jpg (file attached)
"""
IOS = "‎[12/10/26, 2:05:33 PM] Rana: check https://www.aub.edu.lb\n[12/10/26, 2:06:01 PM] Rana: <attached: 00000002-PHOTO.jpg>\n"


def report(verdict: str, score: int) -> dict:
    return {"result": {"verdict": verdict, "final_score": score, "reasons": {}}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(S, "bridge_token", "secret-token")
    wa_api._alerts.clear()
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.get(f"{URLVET}/api/v1/analyze").mock(return_value=httpx.Response(200, json=report("Safe", 90)))
        with TestClient(app) as c:
            c.mock = mock
            yield c


# --- parser -----------------------------------------------------------------------


def test_parse_android_multiline_and_system_lines():
    msgs = parse_text(ANDROID)
    assert [m.sender for m in msgs] == ["Ali", "Unknown", "Ali"]
    assert "omt-gift.example.com" in msgs[1].text  # continuation line joined
    assert msgs[2].attachments == ["IMG-20261012-WA0001.jpg"]


def test_parse_ios_with_invisible_marks():
    msgs = parse_text(IOS)
    assert [(m.sender, m.time) for m in msgs] == [("Rana", "2:05:33 PM"), ("Rana", "2:06:01 PM")]
    assert msgs[1].attachments == ["00000002-PHOTO.jpg"]


def test_load_rejects_non_chat():
    with pytest.raises(ExportRejected):
        load_export("notes.txt", b"just some notes\nwithout dates")


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_load_zip_with_image():
    qr = to_bytes(make_qr("https://omt.com.lb@omt-claim.example.com/x"))
    data = make_zip({"WhatsApp Chat with Rana.txt": IOS.encode(), "00000002-PHOTO.jpg": qr})
    export = load_export("WhatsApp Chat with Rana.zip", data)
    assert export.title == "Rana"
    assert list(export.images) == ["00000002-PHOTO.jpg"]


def test_zip_bomb_rejected():
    data = make_zip({"_chat.txt": IOS.encode(), "big.bin": b"0" * (81 * 1024 * 1024)})
    with pytest.raises(ExportRejected, match="too large"):
        load_export("chat.zip", data)


# --- import endpoint -----------------------------------------------------------------


def test_import_txt_flags_scam_message(client):
    r = client.post("/import/chat", files={"file": ("WhatsApp Chat with Ali.txt", ANDROID.encode(), "text/plain")})
    assert r.status_code == 200
    rep = r.json()
    assert rep["messages_total"] == 3 and rep["title"] == "Ali"
    assert rep["risk_level"] == "High"
    assert rep["findings"][0]["sender"] == "Unknown"
    assert rep["links_checked"] == 1


def test_import_zip_scans_photos(client):
    qr = to_bytes(make_qr("bitcoin:bc1qdemo?amount=1"))
    data = make_zip({"_chat.txt": IOS.encode(), "00000002-PHOTO.jpg": qr})
    rep = client.post("/import/chat", files={"file": ("chat.zip", data, "application/zip")}).json()
    assert rep["images_checked"] == 1
    photo = next(f for f in rep["findings"] if f["attachment"])
    assert photo["sender"] == "Rana" and photo["evidence"]["risk_level"] == "High"


def test_import_link_budget(client, monkeypatch):
    monkeypatch.setattr(S, "max_urls_per_import", 2)
    lines = "\n".join(f"12/10/2026, 14:0{i} - A: see site{i}.com" for i in range(5))
    rep = client.post("/import/chat", files={"file": ("c.txt", lines.encode(), "text/plain")}).json()
    assert rep["links_found"] == 5 and rep["links_checked"] == 2
    assert rep["warnings"]


def test_import_rejects_garbage(client):
    r = client.post("/import/chat", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


# --- live bridge --------------------------------------------------------------------


def test_status_when_bridge_off(client):
    client.mock.get(f"{BRIDGE}/status").mock(side_effect=httpx.ConnectError("off"))
    assert client.get("/whatsapp/status").json() == {"enabled": False}


def test_status_and_selection_proxy(client):
    client.mock.get(f"{BRIDGE}/status").mock(return_value=httpx.Response(200, json={"state": "connected"}))
    sel = client.mock.put(f"{BRIDGE}/selection").mock(return_value=httpx.Response(200, json={"selected": 1}))
    assert client.get("/whatsapp/status").json()["state"] == "connected"
    assert client.put("/whatsapp/selection", json={"chat_ids": ["1@s.whatsapp.net"]}).json() == {"selected": 1}
    assert sel.calls.last.request.content == b'{"chat_ids":["1@s.whatsapp.net"]}'


def test_ingest_requires_token(client):
    form = {"kind": "text", "text": "hi"}
    assert client.post("/whatsapp/ingest", data=form).status_code == 403
    assert client.post("/whatsapp/ingest", data=form, headers={"X-Bridge-Token": "wrong"}).status_code == 403


def test_ingest_stores_only_flagged(client):
    h = {"X-Bridge-Token": "secret-token"}
    ok = client.post("/whatsapp/ingest", headers=h, data={"kind": "text", "chat_name": "Mom", "text": "see you at 8"})
    assert ok.json() == {"stored": False}
    bad = client.post("/whatsapp/ingest", headers=h, data={
        "kind": "text", "chat_name": "Unknown", "sender": "X",
        "text": "Mabrouk rbe7t jeyze, ab3atli el code: omt-gift.example.com"})
    assert bad.json()["stored"] is True
    alerts = client.get("/whatsapp/alerts").json()
    assert len(alerts) == 1 and alerts[0]["chat_name"] == "Unknown"
    assert client.delete("/whatsapp/alerts").json() == {"cleared": True}
    assert client.get("/whatsapp/alerts").json() == []


def test_ingest_image_with_qr(client):
    h = {"X-Bridge-Token": "secret-token"}
    img = to_bytes(make_qr("WIFI:S:Free;T:nopass;;"))
    r = client.post("/whatsapp/ingest", headers=h, data={"kind": "image", "chat_name": "Group"},
                    files={"file": ("w.jpg", img, "image/jpeg")})
    assert r.json()["stored"] is True
