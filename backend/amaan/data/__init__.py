"""Shared rule data. The JSON files must stay byte-identical to packages/core/src/data/
(the phone app runs the same rules; a parity test enforces it)."""

import json
from functools import cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@cache
def load(name: str) -> dict:
    """brands.json, cues.json or lookups.json, parsed once."""
    return json.loads((_DIR / name).read_text(encoding="utf-8"))
