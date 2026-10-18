"""Multi-source link reputation (VirusTotal / URLVoid style).

Each source answers independently (flagged / clean / unknown / not set up)
and Amaan combines the answers into explainable signals. Sources only ever
see the link, never the message or image. See docs/DECISIONS.md (D11).
"""
