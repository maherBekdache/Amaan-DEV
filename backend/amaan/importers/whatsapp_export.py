"""Parse WhatsApp's "Export chat" file (.txt, or .zip with media), in memory.

Formats seen in the wild (date order and separators vary by phone locale):
  Android: 12/10/2026, 14:05 - Ali: message
           12/10/26, 2:05 PM - Ali: message
  iPhone:  [12/10/2026, 14:05:33] Ali: message
           [12/10/26, 2:05:33 PM] Ali: message      (often prefixed by U+200E)
A message continues on the following lines until the next dated line.
Nothing is written to disk.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

MAX_TEXT_BYTES = 20 * 1024 * 1024
MAX_IMAGES = 15
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_UNZIPPED = 80 * 1024 * 1024  # zip-bomb guard
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")

_DATE = r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}"
_TIME = r"\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[APap]\.?\s?[Mm]\.?)?"
_IOS = re.compile(rf"^\[({_DATE}),?\s({_TIME})\]\s(.+?):\s(.*)$")
_ANDROID = re.compile(rf"^({_DATE}),?\s({_TIME})\s[-–]\s(.+?):\s(.*)$")
_SYSTEM = re.compile(rf"^\[?({_DATE}),?\s({_TIME})\]?\s[-–]?\s?[^:]+$")  # "… - Messages are end-to-end encrypted"
_ATTACHED = re.compile(r"<attached:\s*([^>]+)>|(\S+\.(?:jpe?g|png|webp))\s*\(file attached\)", re.IGNORECASE)
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬"), None)


class ExportRejected(ValueError):
    pass


@dataclass
class ChatMessage:
    index: int
    date: str
    time: str
    sender: str
    text: str
    attachments: list[str] = field(default_factory=list)


@dataclass
class ChatExport:
    title: str
    messages: list[ChatMessage]
    images: dict[str, bytes]  # file name -> bytes (only images referenced or present, capped)
    skipped_images: int = 0


def _clean(line: str) -> str:
    return line.translate(_INVISIBLE).replace(" ", " ").replace(" ", " ").rstrip("\r")


def parse_text(text: str) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for raw in text.splitlines():
        line = _clean(raw)
        m = _IOS.match(line) or _ANDROID.match(line)
        if m:
            date, time, sender, body = m.groups()
            messages.append(ChatMessage(len(messages), date, time, sender.strip(), body))
        elif _SYSTEM.match(line):
            continue  # encryption notices, "X added Y", etc.
        elif messages and line.strip():
            messages[-1].text += "\n" + line
    for msg in messages:
        msg.attachments = [a or b for a, b in _ATTACHED.findall(msg.text)]
    return messages


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1256"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def load_export(filename: str, data: bytes) -> ChatExport:
    name = (filename or "chat.txt").rsplit("/", 1)[-1]
    if data[:2] == b"PK":
        return _load_zip(name, data)
    if len(data) > MAX_TEXT_BYTES:
        raise ExportRejected("The chat file is too large.")
    messages = parse_text(_decode(data))
    if not messages:
        raise ExportRejected("This doesn't look like a WhatsApp chat export (no messages found).")
    return ChatExport(title=_title(name), messages=messages, images={})


def _load_zip(name: str, data: bytes) -> ChatExport:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExportRejected("The .zip file is damaged.") from None
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > MAX_TOTAL_UNZIPPED:
        raise ExportRejected("The .zip file is too large once unpacked.")
    texts = [i for i in infos if i.filename.lower().endswith(".txt") and i.file_size <= MAX_TEXT_BYTES]
    if not texts:
        raise ExportRejected("No chat text (.txt) found inside the .zip file.")
    chat_txt = next((i for i in texts if "chat" in i.filename.lower()), max(texts, key=lambda i: i.file_size))
    messages = parse_text(_decode(zf.read(chat_txt)))
    if not messages:
        raise ExportRejected("This doesn't look like a WhatsApp chat export (no messages found).")

    referenced = {a.strip().lower() for m in messages for a in m.attachments}
    candidates = [i for i in infos if i.filename.lower().endswith(IMAGE_EXT) and i.file_size <= MAX_IMAGE_BYTES]
    candidates.sort(key=lambda i: i.filename.rsplit("/", 1)[-1].lower() not in referenced)  # referenced first
    images = {i.filename.rsplit("/", 1)[-1]: zf.read(i) for i in candidates[:MAX_IMAGES]}
    return ChatExport(title=_title(chat_txt.filename.rsplit("/", 1)[-1]), messages=messages,
                      images=images, skipped_images=max(0, len(candidates) - MAX_IMAGES))


def _title(filename: str) -> str:
    base = re.sub(r"\.(txt|zip)$", "", filename, flags=re.IGNORECASE)
    base = re.sub(r"^(WhatsApp Chat (with|-)\s*)", "", base, flags=re.IGNORECASE).strip(" -_")
    return base if base and base.lower() not in ("_chat", "chat") else "WhatsApp chat"
