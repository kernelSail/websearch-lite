"""P3 测试：转载/独立源、状态机、验证器真实库行为、冲突裁决。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.eval.p3_eval import evaluate
from websearch_lite.facts.extractor import FactExtractor
from websearch_lite.storage.sqlite_store import Store
from websearch_lite.verification.source_graph import SourceGraph
from websearch_lite.verification.state import assert_transition, can_transition, decide_status
from websearch_lite.verification.verifier import Verifier

TEXT = ("项目名称：某某医院设备采购项目\n"
        "项目编号：TEST-P3-0001\n"
        "中标供应商：北京示例科技有限公司\n"
        "中标金额：100 万元\n"
        "采购人：某某医院")


def _setup():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
    cfg = {"id": "gov_procurement", "label": "G", "schema_version": "procurement_v1",
           "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                           "base_url": "https://a.cn/", "role": "authoritative"},
           "authority_scope": [], "trust_weight": 1.0}
    store.register_domain(cfg, "x.json")
    return tmp, store


def _ingest(store, url, text, run_id="r"):
    return store.ingest(domain_id="gov_procurement", source_id="s1", url=url,
                        canonical_url=url, title="公告", text=text, published_at=None,
                        fetched_at="2026-11-06T00:00:00Z", http_status=200, etag=None,
                        last_modified=None, extraction_status="success", metadata={},
                        doc_type="procurement", run_id=run_id)


def test_source_graph_repost_and_clusters():
    g = SourceGraph()
    g.add_node("a", fetched_at="2026-11-01T00:00:00Z", source_id="s1", text="相同正文内容测试")
    g.add_node("b", fetched_at="2026-11-02T00:00:00Z", source_id="s2", text="相同正文内容测试")
    assert g.detect_reposts() == 1
    count, _ = g.independent_clusters(["a", "b"])
    assert count == 1
    g.add_node("c", fetched_at="2026-11-03T00:00:00Z", source_id="s3", text="完全不同的内容")
    assert g.independent_clusters(["a", "b", "c"])[0] == 2


def test_unknown_relation_not_merged():
    g = SourceGraph()
    g.add_node("x", text="相同内容", fetched_at="2026-11-01T00:00:00Z", source_id="s1")
    g.add_node("y", text="相同内容", fetched_at="2026-11-02T00:00:00Z", source_id="s2")
    g.add_relation("x", "y", "unknown", 0.3)
    assert g.independent_clusters(["x", "y"])[0] == 2


def test_state_machine():
    assert can_transition("unverified", "verified")
    assert can_transition("conflicting", "verified")
    assert not can_transition("rejected", "verified")
    try:
        assert_transition("rejected", "verified")
        assert False
    except ValueError:
        pass
    assert decide_status({"independent_source_count": 1, "authority_level": "authoritative",
                          "evidence_consistency": "consistent", "freshness": "current",
                          "extraction_quality": "passed"}) == "single-source"


def test_p3_eval_all_pass():
    report = evaluate()
    assert report["passed"] == report["total"] == 15


def test_verify_all_on_real_store():
    tmp, store = _setup()
    try:
        ing = _ingest(store, "https://a.cn/1", TEXT)
        FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=TEXT, run_id="r")
        result = Verifier(store).verify_all()
        assert result["total"] == 5 and not result["errors"]
        assert result["single-source"] == 5  # 单证据 → 单源
        assert store.verification_counts().get("single-source") == 5
        assert store.source_relationships_count() >= 0
    finally:
        tmp.cleanup()


def test_conflict_snapshot_and_resolution():
    tmp, store = _setup()
    try:
        ing = _ingest(store, "https://a.cn/1", TEXT)
        ex = FactExtractor(store, "gov_procurement")
        ex.extract_document(document_version_id=ing["document_version_id"], text=TEXT, run_id="r")
        # 制造同 fact 的第二个不同值版本
        with __import__("contextlib").closing(store._connect()) as db:
            fact = db.execute("SELECT fact_id,predicate FROM facts WHERE predicate='award_amount'").fetchone()
            db.execute(
                """INSERT INTO fact_versions(fact_version_id,fact_id,version_no,value_json,normalized_value,
                     verification_status,schema_version,created_at) VALUES (?,?,?,?,?,'unverified','procurement_v1',?)""",
                ("fv_conflict", fact["fact_id"], 2, "{\"raw\":\"999 元\"}", "999.0", "2026-11-06T00:00:00Z"),
            )
            db.commit()
        Verifier(store).verify_all()
        # 冲突版本应生成快照
        assert len(store.list_conflicts()) >= 1
        conf = store.list_conflicts()[0]
        assert conf["status"] == "open"
        resolved = Verifier(store).resolve_conflict(conf["conflict_id"], "fv_conflict", reason="authoritative correction")
        assert resolved["status"] == "resolved"
        assert store.list_conflicts()[0]["winner_fact_version_id"] == "fv_conflict"
    finally:
        tmp.cleanup()


def test_verify_idempotent():
    tmp, store = _setup()
    try:
        ing = _ingest(store, "https://a.cn/1", TEXT)
        FactExtractor(store, "gov_procurement").extract_document(
            document_version_id=ing["document_version_id"], text=TEXT, run_id="r")
        Verifier(store).verify_all()
        first = store.verification_counts()
        Verifier(store).verify_all()  # 重复验证不应报错（single-source→single-source 合法）
        assert store.verification_counts() == first
    finally:
        tmp.cleanup()
