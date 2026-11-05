"""正文抽取：纯标准库实现（P0 零第三方依赖）。"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_DROP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}


class _TextExtractor(HTMLParser):
    def __init__(self, selectors: list[str] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors or []
        self.parts: list[str] = []
        self.skip_depth = 0
        self.capture_depth = 0
        self.in_capture = not self.selectors
        self._selector_hit = not self.selectors

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if self.capture_depth > 0:
            self.capture_depth += 1
        if tag in _DROP_TAGS:
            self.skip_depth += 1
            return
        if not self._selector_hit and self.selectors:
            classes = (attrs_dict.get("class") or "").split()
            ident = attrs_dict.get("id") or ""
            for selector in self.selectors:
                selector = selector.strip()
                if not selector:
                    continue
                head, _, tail = selector.partition(".")
                if selector.startswith("#"):
                    matched = ident == selector[1:]
                elif selector.startswith("."):
                    matched = selector[1:] in classes
                elif tail:  # "div.article"
                    matched = tag == head and tail in classes
                else:  # "article"
                    matched = tag == selector
                if matched:
                    self._selector_hit = True
                    self.in_capture = True
                    self.capture_depth = 1
                    break
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.capture_depth > 0:
            self.capture_depth -= 1
            if self.capture_depth == 0:
                self.in_capture = False
        if tag in _DROP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0 and self.in_capture:
            self.parts.append(data)


def extract_title(raw: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))).strip()


def extract_text(raw: str, selectors: list[str] | None = None) -> str:
    parser = _TextExtractor(selectors)
    try:
        parser.feed(raw)
    except Exception:
        pass
    text = "".join(parser.parts)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 8]
    return "\n".join(lines).strip()


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def first_evidence(text: str, limit: int = 400) -> str:
    return text[:limit].strip()
