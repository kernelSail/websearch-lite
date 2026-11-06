"""P4 测试：域路由、过滤、去重、重排、引用完整性、评测、CLI 结果结构。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.eval.p4_eval import evaluate
from websearch_lite.query.coordinator import QueryCoordinator
from websearch_lite.storage.sqlite_store import Store

TEXT = ("项目名称：某某医院设备采购项目\n项目编号：P4-TEST-001\n"
        "中标供应商：示例公司\n中标金额：100 万元")


def _store():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
    cfg = {"id": "gov_procurement", "label": "G", "schema_version": "procurement_v1",
           "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                           "base_url": "https://a.cn/", "role": "authoritative"},
           "authority_scope": [], "trust_weight": 1.0}
    store.register_domain(cfg, "x.json")
    for i in range(3):
        store.ingest(domain_id="gov_procurement", source_id="s1",
                     url=f"https://a.cn/{i}", canonical_url=f"https://a.cn/{i}",
                     title=f"招标公告 {i}", text=TEXT + str(i), published_at=None,
                     fetched_at="2026-11-06T00:00:00Z", http_status=200, etag=None,
                     last_modified=None, extraction_status="success", metadata={},
                     doc_type="procurement", run_id="r")
    return tmp, store


def test_route_by_keyword():
    tmp, store = _store()
    try:
        c = QueryCoordinator(store, {"search_engine": "fts5"})
        assert c.route("采购公告") == ["gov_procurement"]
        assert c.route("随便查查") == ["gov_procurement"]  # 仅一个已启用域
    finally:
        tmp.cleanup()


def test_search_returns_answer_and_citations():
    tmp, store = _store()
    try:
        c = QueryCoordinator(store, {"search_engine": "fts5"})
        result = c.search("招标", filters={"domain_id": "gov_procurement"}, limit=5)
        assert result["results"] and result["answer"].startswith("查询：")
        assert result["citations_valid"] is True
        assert all("final_score" in r for r in result["results"])
    finally:
        tmp.cleanup()


def test_structural_filters():
    tmp, store = _store()
    try:
        c = QueryCoordinator(store, {"search_engine": "fts5"})
        r1 = c.search("招标", filters={"since": "2030-01-01"})
        assert r1["results"] == []
        r2 = c.search("招标", filters={"title_contains": "招标公告 1"})
        assert all("招标公告 1" in (x.get("title") or "") for x in r2["results"])
    finally:
        tmp.cleanup()


def test_citation_validation_rejects_missing_url():
    assert QueryCoordinator._validate_citations([{"canonical_url": "https://a.cn", "document_version_id": "v"}])
    assert not QueryCoordinator._validate_citations([{"canonical_url": "", "document_version_id": "v"}])


def test_eval4_metrics_bounded():
    tmp, store = _store()
    try:
        report = evaluate(QueryCoordinator(store, {"search_engine": "fts5"}))
        assert report["total"] == 5
        assert 0.0 <= report["ndcg_at_k"] <= 1.0
        assert 0.0 <= report["recall_at_k"] <= 1.0
        assert 0.0 <= report["citation_accuracy"] <= 1.0
    finally:
        tmp.cleanup()


def test_ask_answer_has_no_unbound_claims():
    tmp, store = _store()
    try:
        c = QueryCoordinator(store, {"search_engine": "fts5"})
        result = c.search("不存在的词", limit=5)
        assert "没有命中" in result["answer"]
    finally:
        tmp.cleanup()
