"""Pull links and visible text out of dropped/pasted HTML.

The HTML is only *parsed* with the standard-library tokenizer. It is never
rendered, no resources (images, scripts, styles) are loaded, and no
JavaScript runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_HTML_CHARS = 200_000


@dataclass
class HtmlLink:
    href: str
    text: str


@dataclass
class HtmlContent:
    text: str
    links: list[HtmlLink] = field(default_factory=list)


class _Parser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[HtmlLink] = []
        self._skip = 0
        self._href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href") or None
            self._anchor_text = []
        elif tag in ("br", "p", "div", "li", "tr"):
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.links.append(HtmlLink(self._href.strip(), " ".join("".join(self._anchor_text).split())))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text_parts.append(data)
        if self._href is not None:
            self._anchor_text.append(data)


def parse_html(html: str) -> HtmlContent:
    parser = _Parser()
    parser.feed(html[:MAX_HTML_CHARS])
    parser.close()
    return HtmlContent(text="".join(parser.text_parts), links=parser.links)
