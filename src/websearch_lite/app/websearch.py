"""联网元搜索：Bing HTML 端点（零依赖），搜狗备用。

定位：补足「本地库没有的内容」——先联网拿结果，用户可选入库沉淀。
不绕过反爬：带正常 UA、低频、遵守 robots 语义（Bing HTML 端点公开可访问）。
"""
from __future__ import annotations

import gzip
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 15


class _BingParser(HTMLParser):
    """解析 Bing 结果页：li.b_algo → h2>a(href,title) + p(摘要)。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._in_algo = 0
        self._in_h2 = False
        self._in_a = False
        self._in_p = False
        self._url = ""
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "li" and "b_algo" in classes:
            self._in_algo = 1
            self._url = ""
            self._title_parts = []
            self._snippet_parts = []
            return
        if not self._in_algo:
            return
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2:
            self._in_a = True
            self._url = attr.get("href") or ""
        elif tag == "p":
            self._in_p = True

    def handle_endtag(self, tag: str) -> None:
        if not self._in_algo:
            return
        if tag == "a":
            self._in_a = False
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p":
            self._in_p = False
        elif tag == "li":
            title = re.sub(r"\s+", " ", "".join(self._title_parts)).strip()
            snippet = re.sub(r"\s+", " ", "".join(self._snippet_parts)).strip()
            if title and self._url:
                self.items.append({"title": title, "url": self._url, "snippet": snippet})
            self._in_algo = 0

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._title_parts.append(data)
        if self._in_p:
            self._snippet_parts.append(data)


class _SogouParser(HTMLParser):
    """搜狗结果页：h3>a + .str_info / .space-txt 摘要。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._in_h3 = False
        self._in_a = False
        self._in_snippet = False
        self._url = ""
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._pending = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "")
        if tag == "h3":
            self._in_h3 = True
            self._pending = True
            self._url = ""
            self._title_parts = []
            self._snippet_parts = []
        elif tag == "a" and self._in_h3:
            self._in_a = True
            self._url = attr.get("href") or ""
        elif any(k in classes for k in ("str_info", "space-txt", "text-layout")):
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_a = False
        elif tag == "h3":
            self._in_h3 = False
        elif tag in ("div", "p") and self._in_snippet:
            self._in_snippet = False
            if self._pending and self._url and self._title_parts:
                title = re.sub(r"\s+", " ", "".join(self._title_parts)).strip()
                snippet = re.sub(r"\s+", " ", "".join(self._snippet_parts)).strip()
                if title and self._url.startswith("http"):
                    self.items.append({"title": title, "url": self._url, "snippet": snippet})
                self._pending = False

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._title_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)


def _fetch(url: str, *, referer: str | None = None) -> str:
    headers = {
        "user-agent": DEFAULT_UA,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "accept-encoding": "gzip, deflate",
    }
    if referer:
        headers["referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("content-encoding") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    for charset in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(charset)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean_bing_url(url: str) -> str:
    """Bing 会包一层 bing.com/ck/a?...&u=a1<base64>，尽量还原真实 URL。"""
    if "bing.com/ck/a" not in url:
        return url
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    target = (query.get("u") or [""])[0]
    if target.startswith("a1"):
        import base64

        payload = target[2:]
        payload += "=" * (-len(payload) % 4)
        try:
            return base64.urlsafe_b64decode(payload).decode("utf-8", errors="replace")
        except Exception:
            return url
    return url


def search_bing(query: str, *, limit: int = 10, mkt: str = "zh-CN") -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "count": str(limit), "setlang": mkt})
    html = _fetch(f"https://www.bing.com/search?{params}")
    parser = _BingParser()
    parser.feed(html)
    out = []
    seen = set()
    for item in parser.items:
        url = _clean_bing_url(item["url"])
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append({**item, "url": url, "engine": "bing"})
        if len(out) >= limit:
            break
    return out


def search_sogou(query: str, *, limit: int = 10) -> list[dict]:
    params = urllib.parse.urlencode({"query": query})
    html = _fetch(f"https://www.sogou.com/web?{params}")
    parser = _SogouParser()
    parser.feed(html)
    out = []
    seen = set()
    for item in parser.items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        out.append({**item, "engine": "sogou"})
        if len(out) >= limit:
            break
    return out


def web_search(query: str, *, limit: int = 10) -> dict:
    """联网搜索：Bing 优先，搜狗备用，全部失败返回空并说明原因。"""
    errors = []
    for name, fn in (("bing", search_bing), ("sogou", search_sogou)):
        started = time.perf_counter()
        try:
            results = fn(query, limit=limit)
            latency = int((time.perf_counter() - started) * 1000)
            if results:
                return {"query": query, "engine": name, "results": results,
                        "latency_ms": latency, "errors": errors}
            errors.append(f"{name}: empty")
        except Exception as error:
            errors.append(f"{name}: {type(error).__name__}: {str(error)[:120]}")
    return {"query": query, "engine": None, "results": [], "latency_ms": 0, "errors": errors}
