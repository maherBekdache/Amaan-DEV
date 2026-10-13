"""Regenerate the example QR images from frontend/src/examples.json.

Run from the repo root:  backend/.venv/bin/python scripts/make_examples.py
"""

import json
import random
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "frontend" / "src" / "examples.json"
OUT = ROOT / "frontend" / "public" / "examples"


def qr(data: str, box: int = 10) -> Image.Image:
    q = qrcode.QRCode(box_size=box, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(data)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white").convert("RGB")


def main() -> None:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    for s in samples["qr"]:
        qr(s["payload"]).save(OUT / s["file"])

    multi = samples["qr_multi"]
    imgs = [qr(p, box=7) for p in multi["payloads"]]
    canvas = Image.new("RGB", (sum(i.width for i in imgs) + 60 * (len(imgs) + 1), max(i.height for i in imgs) + 120), "white")
    x = 60
    for i in imgs:
        canvas.paste(i, (x, 60))
        x += i.width + 60
    canvas.save(OUT / multi["file"])

    # A "photo" of a poster: grey noisy background, small tilted QR, slight blur.
    rnd = random.Random(7)
    photo = Image.new("RGB", (1600, 1200), (172, 168, 160))
    draw = ImageDraw.Draw(photo)
    for _ in range(4000):
        x, y = rnd.randrange(1600), rnd.randrange(1200)
        c = rnd.randrange(120, 210)
        draw.point((x, y), fill=(c, c, c))
    draw.rectangle((420, 220, 1180, 1000), fill=(245, 240, 230))
    code = qr(samples["qr_photo"]["payload"], box=6).rotate(8, expand=True, fillcolor=(245, 240, 230))
    photo.paste(code, (560, 380))
    photo.filter(ImageFilter.GaussianBlur(1.2)).save(OUT / samples["qr_photo"]["file"], quality=82)
    print(f"Wrote QR samples to {OUT}")


if __name__ == "__main__":
    main()
