import io

import pytest
import qrcode
from PIL import Image


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
