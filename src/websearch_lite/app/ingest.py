"""把任意 URL 抓取并沉淀到本地库（联网搜索结果的「入库」动作）。

走与站点采集相同的处理链路：robots → 抓取 → 正文抽取 → 去重 → 入库 → 重建索引。
收录内容归入 adhoc 域（用户主动收录的网页），与定向采集域区分。
"""
from __future__ import annotations

import json
from contextlib import closing

from ..common import canonicalize_url, now_iso
from ..crawler.adapters import build_adapter
from ..crawler.fetcher import Fetcher

ADHOC_ID = "adhoc"
ADHOC_DOMAIN = {
    "id": ADHOC_ID,
    "label": "网页收录",
    "schema_version": "generic_v1",
    "storage_path": "",
    "source": {"id": "adhoc_web", "name": "Web 收录", "base_url": "https://", "role": "reference"},
    "authority_scope": [],
    "trust_weight": 0.6,
}


def ensure_adhoc(store) -> None:
    """幂等注册 adhoc 域与来源。"""
    with closing(store._connect()) as db:
        if db.execute("SELECT 1 FROM domains WHERE domain_id=?", (ADHOC_ID,)).fetchone():
            return
    try:
        store.register_domain(ADHOC_DOMAIN, json.dumps(
            {"id": ADHOC_ID, "label": "网页收录", "schema_version": "generic_v1",
             "enabled": True}, ensure_ascii=False))
    except Exception:
        # 已存在或外键顺序问题：直接补一条域名记录
        with closing(store._connect()) as db:
            db.execute("INSERT OR IGNORE INTO domains VALUES (?,?,?,?,?,1,?,?)",
                       (ADHOC_ID, "网页收录", "generic_v1", "", "", now_iso(), now_iso()))
            db.commit()


def ingest_url(store, config: dict, *, url: str, run_id: str | None = None) -> dict:
    """抓取单条 URL 并入库；返回入库结果。"""
    ensure_adhoc(store)
    fetcher = Fetcher(config)
    adapter = build_adapter("generic")
    result = fetcher.fetch(url, rps=1.0, respect_robots=True, base_url=url)
    if result.error or not result.body:
        return {"ok": False, "error": result.error or "EMPTY_BODY", "url": url}
    raw = result.body.decode("utf-8", errors="replace")
    content = adapter.extract_content(raw, url, [])
    title = content["title"] or url
    text = content["text"]
    if not text:
        return {"ok": False, "error": "EXTRACTION_FAILED", "url": url}
    ingested = store.ingest(
        domain_id=ADHOC_ID, source_id=ADHOC_DOMAIN["source"]["id"],
        url=url, canonical_url=canonicalize_url(url), title=title, text=text,
        published_at=None, fetched_at=result.fetched_at,
        http_status=result.status_code, etag=result.headers.get("etag"),
        last_modified=result.headers.get("last-modified"),
        extraction_status=content["extraction_status"], metadata={"title": title, "url": url},
        doc_type="other", run_id=run_id or "adhoc",
        snippet_limit=int(config["p0"]["max_snippet_chars"]),
        evidence_limit=int(config["p0"]["max_evidence_chars"]),
    )
    return {"ok": True, "document_id": ingested.get("document_id"), "title": title,
            "document_version_id": ingested.get("document_version_id"),
            "new_version": ingested.get("new_version"), "chars": len(text)}
