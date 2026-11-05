"""P0 测试：使用本地 fixture，不打真实网络。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from websearch_lite.paths import find_project_root
ROOT = find_project_root()

from websearch_lite.common import canonicalize_url, hamming, simhash
from websearch_lite.crawler.adapters import GenericAdapter
from websearch_lite.pipeline.extract import extract_text, extract_title
from websearch_lite.storage.sqlite_store import Store

FIXTURE = ROOT / "scripts" / "fixtures" / "sample.html"


def test_canonicalize():
    assert canonicalize_url("https://www.Example.com/a//b/amp?utm_source=x&id=7#frag") == "https://example.com/a/b?id=7"


def test_simhash_near_duplicate():
    assert hamming(simhash("同一条新闻内容"), simhash("同一条新闻内容。")) <= 3


def test_extract():
    html = FIXTURE.read_text(encoding="utf-8")
    assert extract_title(html) == "测试公告标题"
    text = extract_text(html, ["div.article"])
    assert "这是一段足够长的正文内容" in text
    assert "导航首页" not in text


def test_adapter_discovers_links():
    html = FIXTURE.read_text(encoding="utf-8")
    urls = GenericAdapter().discover_urls(html, "https://example.com/list/", 10)
    assert any("detail.html" in u for u in urls)


def test_register_and_ingest_idempotent(store):
    config = {
        "id": "test_domain", "label": "测试域", "schema_version": "v1",
        "storage_path": str(ROOT / "domains" / "test_domain"),
        "source": {"id": "test_src", "name": "测试源", "base_url": "https://example.com/", "role": "authoritative"},
        "authority_scope": ["notice"], "trust_weight": 1.0,
    }
    store.register_domain(config, "domain.json")
    assert len(store.list_domains()) == 1

    common = dict(domain_id="test_domain", source_id="test_src",
                  url="https://example.com/a", canonical_url="https://example.com/a",
                  title="标题", text="这是一段足够长的正文内容用于测试入库与幂等性。",
                  published_at="2026-11-01T00:00:00Z", fetched_at="2026-11-05T00:00:00Z",
                  http_status=200, etag=None, last_modified=None,
                  extraction_status="success", metadata={}, doc_type="notice", run_id="run_test")
    first = store.ingest(**common)
    second = store.ingest(**common)
    assert first["new_version"] is True
    assert second["new_version"] is False  # 同 hash 复用
    assert first["document_version_id"] == second["document_version_id"]
    assert store.stats()["documents"] == 1
    assert store.stats()["document_versions"] == 1


def test_search_fallback_and_domain_filter(store):
    config = {
        "id": "d1", "label": "D1", "schema_version": "v1", "storage_path": "x",
        "source": {"id": "s1", "name": "S1", "base_url": "https://a.cn/", "role": "reference"},
    }
    store.register_domain(config, "d1.json")
    store.ingest(domain_id="d1", source_id="s1", url="https://a.cn/p", canonical_url="https://a.cn/p",
                 title="企业信息查询", text="企业信息查询平台正文内容足够长用于检索测试。",
                 published_at=None, fetched_at="2026-11-05T00:00:00Z", http_status=200,
                 etag=None, last_modified=None, extraction_status="success", metadata={},
                 doc_type="notice", run_id="r")
    assert store.search("企业信息")
    assert store.search("企业信息", domain_id="d1")
    assert not store.search("企业信息", domain_id="other")


def test_consistency_and_crawl_tasks(store):
    config = {
        "id": "d1", "label": "D1", "schema_version": "v1", "storage_path": "x",
        "source": {"id": "s1", "name": "S1", "base_url": "https://a.cn/", "role": "reference"},
    }
    store.register_domain(config, "d1.json")
    assert store.enqueue_url("s1", "https://a.cn/p", "https://a.cn/p") is True
    assert store.enqueue_url("s1", "https://a.cn/p", "https://a.cn/p") is False  # 幂等
    assert len(store.next_crawl_tasks("s1", 10)) == 1
    assert store.consistency()["missing_index"] == []
