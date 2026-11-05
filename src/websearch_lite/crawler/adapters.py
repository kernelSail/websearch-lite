"""站点适配器：站点特有的 URL 发现与字段解析。"""
from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urljoin

from ..common import canonicalize_url
from ..pipeline.extract import extract_text, extract_title


class SiteAdapter(Protocol):
    def discover_urls(self, html: str, base_url: str, limit: int) -> list[str]: ...
    def extract_metadata(self, html: str, url: str) -> dict: ...
    def extract_content(self, html: str, url: str, selectors: list[str]) -> dict: ...
    def classify_document_type(self, metadata: dict, text: str) -> str: ...


class GenericAdapter:
    """两个站点的通用实现：列表页链接发现 + 标题/正文/日期解析。"""

    LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.I)
    DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
    TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

    def discover_urls(self, html: str, base_url: str, limit: int) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for href in self.LINK_RE.findall(html):
            if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
                continue
            absolute = urljoin(base_url, href)
            if not absolute.startswith("http"):
                continue
            canonical = canonicalize_url(absolute)
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append(absolute)
            if len(out) >= limit:
                break
        return out

    def extract_metadata(self, html: str, url: str) -> dict:
        title = extract_title(html)
        published = None
        match = self.DATE_RE.search(html)
        if match:
            published = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}T00:00:00Z"
        return {"title": title, "published_at": published, "url": url}

    def extract_content(self, html: str, url: str, selectors: list[str]) -> dict:
        text = extract_text(html, selectors)
        if len(text) < 40:  # 选择器没命中时兜底整页
            text = extract_text(html)
        title = extract_title(html)
        return {
            "title": title,
            "text": text,
            "paragraphs": [p for p in text.split("\n") if p.strip()],
            "extraction_status": "success" if len(text) >= 80 else "partial",
        }

    def classify_document_type(self, metadata: dict, text: str) -> str:
        blob = (metadata.get("title", "") + " " + text[:300]).lower()
        if any(k in blob for k in ("中标", "成交", "招标", "采购")):
            return "procurement"
        if any(k in blob for k in ("公告", "年报", "报告", "披露")):
            return "announcement"
        return "other"


class CcgpAdapter(GenericAdapter):
    def discover_urls(self, html: str, base_url: str, limit: int) -> list[str]:
        urls = super().discover_urls(html, base_url, limit)
        return [u for u in urls if "ccgp.gov.cn" in u and re.search(r"/\d{4,}|\.htm|\.html", u)]


class CninfoAdapter(GenericAdapter):
    """巨潮资讯网：列表页是 SPA 模板，正文走公告查询 API + PDF 元数据。"""

    API = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

    def discover_api(self, limit: int = 30) -> list[dict]:
        from datetime import datetime, timedelta, timezone
        import json
        import urllib.parse
        import urllib.request

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        payload = urllib.parse.urlencode({
            "pageNum": 1, "pageSize": min(limit, 30), "column": "szse", "tabName": "fulltext",
            "plate": "", "stock": "", "searchkey": "", "secid": "", "category": "", "trade": "",
            "seDate": f"{start}~{today}", "sortName": "", "sortType": "", "isHLtitle": "true",
        }).encode()
        req = urllib.request.Request(self.API, data=payload, headers={
            "User-Agent": "websearch-lite/0.1 (personal)", "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json", "Referer": "http://www.cninfo.com.cn/",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            return []
        out = []
        for item in (data.get("announcements") or [])[:limit]:
            title = item.get("announcementTitle", "")
            adjunct = item.get("adjunctUrl", "")
            if not title:
                continue
            url = "http://static.cninfo.com.cn/" + adjunct.lstrip("/")
            out.append({
                "url": url,
                "title": title,
                "published_at": item.get("announcementTime"),
                "pdf": adjunct.lower().endswith(".pdf"),
                "sec_name": item.get("secName", ""),
                "sec_code": item.get("secCode", ""),
            })
        return out

    def discover_urls(self, html: str, base_url: str, limit: int) -> list[str]:
        # SPA 列表页无有效正文链接，交给 API 路径（在 crawl 层调用 discover_api）
        return []


def build_adapter(name: str) -> SiteAdapter:
    if name == "ccgp":
        return CcgpAdapter()
    if name == "cninfo":
        return CninfoAdapter()
    return GenericAdapter()
