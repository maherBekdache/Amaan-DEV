"""Decode QR codes from an uploaded image, entirely in memory.

Uploads are never written to disk by this module. Decoders are tried in
order of robustness (WeChat CNN detector, OpenCV's classic detector, then
zbar), and their results are merged, so one image can hold several codes.
Whatever a QR code contains is untrusted: this module only returns the text.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
DECODE_MAX_SIDE = 3000  # bigger images are scaled down before decoding


class ImageRejected(ValueError):
    """The upload is not an image we accept (wrong type, too big, corrupt)."""


@dataclass
class DecodedQR:
    text: str
    decoders: list[str]


@dataclass
class QRResult:
    codes: list[DecodedQR]
    width: int
    height: int
    format: str
    elapsed_ms: int


# --- image loading -----------------------------------------------------------


def load_image(data: bytes, max_pixels: int) -> tuple[np.ndarray, str, tuple[int, int]]:
    """Validate and decode image bytes into a grayscale numpy array."""
    if not data:
        raise ImageRejected("The file is empty.")
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ImageRejected(f"Unsupported image type '{fmt or 'unknown'}'. Use PNG, JPG or WebP.")
            w, h = img.size
            if w * h > max_pixels:
                raise ImageRejected(f"Image is too large ({w}x{h} pixels).")
            img = ImageOps.exif_transpose(img)  # phone photos are often rotated
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                img = Image.alpha_composite(bg, img)  # transparent QR on white
            gray = img.convert("L")
            arr = np.asarray(gray, dtype=np.uint8).copy()
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("Image is too large to process safely.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageRejected("The file is not a valid image or is corrupted.") from None
    return arr, fmt, (w, h)


# --- decoders ------------------------------------------------------------------

_lock = threading.Lock()  # OpenCV detector objects are not thread-safe
_wechat = None
_wechat_tried = False


def _get_wechat(model_dir: str | None):
    global _wechat, _wechat_tried
    if _wechat_tried:
        return _wechat
    _wechat_tried = True
    if not hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        return None
    try:
        if model_dir and Path(model_dir, "detect.prototxt").exists():
            d = Path(model_dir)
            _wechat = cv2.wechat_qrcode_WeChatQRCode(
                str(d / "detect.prototxt"), str(d / "detect.caffemodel"),
                str(d / "sr.prototxt"), str(d / "sr.caffemodel"),
            )
        else:
            _wechat = cv2.wechat_qrcode_WeChatQRCode()
    except cv2.error:
        log.warning("WeChat QR detector could not be initialised")
        _wechat = None
    return _wechat


def _pyzbar():
    try:
        from pyzbar import pyzbar

        return pyzbar
    except Exception:  # ImportError, or the zbar DLL/shared library is missing
        return None


def available_decoders(model_dir: str | None = None) -> dict[str, bool]:
    return {
        "wechat": _get_wechat(model_dir) is not None,
        "opencv": hasattr(cv2, "QRCodeDetector"),
        "pyzbar": _pyzbar() is not None,
    }


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "cp1256", "latin-1"):  # cp1256 = Windows Arabic
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run_wechat(img: np.ndarray, model_dir: str | None) -> list[str]:
    det = _get_wechat(model_dir)
    if det is None:
        return []
    try:
        texts, _ = det.detectAndDecode(img)
    except cv2.error:
        return []
    return [t for t in texts if t]


def _run_opencv(img: np.ndarray) -> list[str]:
    det = cv2.QRCodeDetector()
    out: list[str] = []
    try:
        ok, texts, _, _ = det.detectAndDecodeMulti(img)
        if ok:
            out.extend(t for t in texts if t)
    except cv2.error:
        pass
    if not out:
        try:
            text, _, _ = det.detectAndDecode(img)
            if text:
                out.append(text)
        except cv2.error:
            pass
    return out


def _run_pyzbar(img: np.ndarray) -> list[str]:
    zb = _pyzbar()
    if zb is None:
        return []
    try:
        results = zb.decode(img, symbols=[zb.ZBarSymbol.QRCODE])
    except Exception:
        return []
    return [_decode_bytes(r.data) for r in results if r.data]


def _variants(img: np.ndarray):
    """Yield progressively more aggressive versions of the image."""
    h, w = img.shape[:2]
    scale = min(1.0, DECODE_MAX_SIDE / max(h, w))
    base = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
    yield "original", base
    if max(base.shape[:2]) < 1000:
        yield "upscaled", cv2.resize(base, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, otsu = cv2.threshold(base, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "threshold", otsu
    yield "inverted", cv2.bitwise_not(base)  # light-on-dark QR codes


def decode_qr_codes(
    data: bytes,
    *,
    max_pixels: int = 40_000_000,
    max_codes: int = 10,
    model_dir: str | None = None,
) -> QRResult:
    """Find and decode every QR code in an image. Raises ImageRejected."""
    t0 = time.perf_counter()
    gray, fmt, (w, h) = load_image(data, max_pixels)
    found: dict[str, DecodedQR] = {}
    with _lock:
        for _name, variant in _variants(gray):
            for dec_name, fn in (
                ("wechat", lambda im: _run_wechat(im, model_dir)),
                ("opencv", _run_opencv),
                ("pyzbar", _run_pyzbar),
            ):
                for text in fn(variant):
                    text = text.strip("\x00")
                    if text in found:
                        if dec_name not in found[text].decoders:
                            found[text].decoders.append(dec_name)
                    else:
                        found[text] = DecodedQR(text=text, decoders=[dec_name])
            if found:
                break  # no need for more aggressive variants
    codes = list(found.values())[:max_codes]
    return QRResult(
        codes=codes, width=w, height=h, format=fmt,
        elapsed_ms=int((time.perf_counter() - t0) * 1000),
    )
