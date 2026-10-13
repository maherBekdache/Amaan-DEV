"""A FAKE URL.vet for development on laptops that cannot run Docker.

Never use it for the demo video or for real results: it does not contact
anything and invents its verdicts from simple keyword rules. Amaan detects it
(/health returns "mock": true) and shows "MOCK URL.vet" in the UI and on
every result.

Run:  uvicorn devtools.mock_urlvet:app --host 127.0.0.1 --port 8080
"""

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException

app = FastAPI(title="MOCK URL.vet (fake results)")

RISKY_WORDS = ("login", "verify", "gift", "claim", "prize", "secure", "update", "wallet", "bonus")
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "cutt.ly", "rb.gy", "is.gd", "shorturl.at")
NOTE = "MOCK URL.vet: this is a fake result for development, no real scan was done."


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


@app.get("/api/v1/analyze")
def analyze(url: str = ""):
    if not url:
        raise HTTPException(400, {"error": "url query param is required"})
    low = url.lower()
    host = urlsplit(low if "://" in low else "//" + low).hostname or ""
    if host in SHORTENERS:
        verdict, score, bad = "Suspicious", 45, ["[mock] Short link: destination not followed by the mock."]
    elif any(w in low for w in RISKY_WORDS):
        verdict, score, bad = "Risky", 15, ["[mock] Link contains a word often used in phishing."]
    else:
        verdict, score, bad = "Safe", 85, []
    return {
        "_mock": True,
        "url": url,
        "threat_feeds": {"listed": "phish" in low, "sources": ["MOCK list"] if "phish" in low else []},
        "result": {
            "verdict": verdict, "final_score": score, "trust_score": score, "risk_score": 100 - score,
            "reasons": {"bad_reasons": bad or None, "good_reasons": None, "neutral_reasons": [NOTE]},
        },
        "incomplete": False,
    }
