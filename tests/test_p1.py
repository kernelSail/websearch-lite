"""P1 测试：Tantivy 投影的增删、重建、域分离、中文查询。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.indexing.tantivy_port import TantivySearchPort, tokenize

DOCS = [
    {"doc_id": "d1", "document_id": "d1", "domain_id": "gov", "source_id": "s1",
     "title": "中标公告", "snippet": "政府采购中标结果公告", "entities": "",
     "url": "https://a.cn/1", "canonical_url": "https://a.cn/1",
     "document_version_id": "v1", "fetched_at": "2026-11-05T00:00:00Z", "published_at": ""},
    {"doc_id": "d2", "document_id": "d2", "domain_id": "gov", "source_id": "s1",
     "title": "招标公告", "snippet": "医院设备采购招标", "entities": "",
     "url": "https://a.cn/2", "canonical_url": "https://a.cn/2",
     "document_version_id": "v2", "fetched_at": "2026-11-05T00:00:00Z", "published_at": ""},
    {"doc_id": "d3", "document_id": "d3", "domain_id": "listed", "source_id": "s2",
     "title": "年度报告", "snippet": "上市公司年度报告披露", "entities": "",
     "url": "https://b.cn/3", "canonical_url": "https://b.cn/3",
     "document_version_id": "v3", "fetched_at": "2026-11-05T00:00:00Z", "published_at": ""},
]


def test_tokenize_chinese():
    assert "中标" in tokenize("中标公告") or "中" in tokenize("中标公告")


def test_rebuild_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        port = TantivySearchPort(Path(tmp) / "idx")
        port.rebuild(DOCS)
        assert port.stats()["total"] == 3
        assert port.search("中标公告")
        assert port.search("采购")
        assert port.search("年度报告", filters={"domain_id": "listed"})


def test_upsert_delete():
    with tempfile.TemporaryDirectory() as tmp:
        port = TantivySearchPort(Path(tmp) / "idx")
        port.rebuild([])
        port.upsert("d1", DOCS[0])
        assert port.stats()["total"] == 1
        port.delete("d1", domain_id="gov")
        assert port.stats()["total"] == 0


def test_domain_separation():
    with tempfile.TemporaryDirectory() as tmp:
        port = TantivySearchPort(Path(tmp) / "idx")
        port.rebuild(DOCS)
        rows = port.search("公告", filters={"domain_id": "listed"})
        assert all(r["domain_id"] == "listed" for r in rows)


def test_rebuild_replaces_old():
    with tempfile.TemporaryDirectory() as tmp:
        port = TantivySearchPort(Path(tmp) / "idx")
        port.rebuild(DOCS)
        assert port.stats()["total"] == 3
        port.rebuild(DOCS[:1])
        assert port.stats()["total"] == 1


def test_reload_persists():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "idx"
        port = TantivySearchPort(root)
        port.rebuild(DOCS)
        reopened = TantivySearchPort(root)
        assert reopened.stats()["total"] == 3
