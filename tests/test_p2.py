"""P2 测试：规范化、实体解析、抽取落库、幂等、评测。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.facts.extractor import FactExtractor, RuleClassifier, load_schema
from websearch_lite.facts.normalize import find_span, normalize_date, normalize_money, normalize_value
from websearch_lite.storage.sqlite_store import Store

TEXT = ("项目名称：某某医院设备采购项目\n"
        "项目编号：11011726210200012540-XM001\n"
        "中标供应商：北京示例科技有限公司\n"
        "中标金额：1,234.56 万元\n"
        "采购人：某某医院")


def _store():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
    cfg = {"id": "gov_procurement", "label": "政府采购", "schema_version": "procurement_v1",
           "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                           "base_url": "https://a.cn/", "role": "authoritative"},
           "authority_scope": [], "trust_weight": 1.0}
    store.register_domain(cfg, "x.json")
    return tmp, store


def _ingest(store, url, text, run_id):
    return store.ingest(domain_id="gov_procurement", source_id="s1", url=url,
                        canonical_url=url, title="中标公告", text=text, published_at=None,
                        fetched_at="2026-11-05T00:00:00Z", http_status=200, etag=None,
                        last_modified=None, extraction_status="success", metadata={},
                        doc_type="procurement", run_id=run_id)


def test_money_normalization():
    assert normalize_money("1,234.56 万元")["amount"] == 12345600.0
    assert normalize_money("0.98 亿元")["amount"] == 98000000.0
    assert normalize_money("500 元")["amount"] == 500.0
    assert normalize_value("money", "abc")["error"] == "UNPARSEABLE_MONEY"


def test_date_normalization():
    assert normalize_date("1793849738000") == "2026-11-05"
    assert normalize_date("2026年11月5日") == "2026-11-05"
    assert normalize_date("not-a-date") is None


def test_evidence_span():
    start, end, quote = find_span(TEXT, "中标金额：1,234.56 万元")
    assert end > start and "中标金额" in quote


def test_rule_classifier_fields():
    result = RuleClassifier(load_schema("gov_procurement")).classify(TEXT)
    assert set(result["fields"]) >= {"project_name", "project_code", "winner", "award_amount", "purchaser"}
    assert result["fields"]["award_amount"]["normalized"] == "12345600.0"
    assert all(not f["error"] for f in result["fields"].values())


def test_extract_creates_facts_and_evidence():
    tmp, store = _store()
    try:
        ing = _ingest(store, "https://a.cn/1", TEXT, "r1")
        result = FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=TEXT,
            metadata={"source_id": "s1"}, run_id="r1")
        assert result["candidates"] == 5 and result["created"] == 5
        assert result["needs_review"] is False
        stats = store.stats()
        assert stats["facts"] == 5 and stats["fact_versions"] == 5
        assert stats["fact_evidences"] >= 5 and stats["raw_fact_candidates"] == 5
        FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=TEXT,
            metadata={"source_id": "s1"}, run_id="r1")
        assert store.stats()["fact_versions"] == 5  # 幂等
    finally:
        tmp.cleanup()


def test_no_stable_id_creates_review():
    tmp, store = _store()
    try:
        text = "中标供应商：北京示例科技有限公司\n中标金额：100 万元"
        ing = _ingest(store, "https://a.cn/2", text, "r2")
        result = FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=text, run_id="r2")
        assert result["needs_review"] is True
        assert store.stats()["review_tasks"] >= 1
    finally:
        tmp.cleanup()


def test_p2_eval():
    from websearch_lite.eval.p2_eval import evaluate
    report = evaluate()
    assert report["overall"]["f1"] == 1.0
    assert report["evidence_valid_rate"] == 1.0
    assert report["normalization_passed"] == 6


def test_list_facts():
    tmp, store = _store()
    try:
        ing = _ingest(store, "https://a.cn/3", TEXT, "r3")
        FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=TEXT, run_id="r3")
        rows = store.list_facts(domain_id="gov_procurement")
        assert len(rows) == 5 and any(r["predicate"] == "award_amount" for r in rows)
    finally:
        tmp.cleanup()
