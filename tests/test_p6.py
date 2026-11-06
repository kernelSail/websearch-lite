"""P6 测试：常驻调度一轮、增量到期过滤、分类器降级、restore 前自动备份、I/O 探活。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.daemon import run_once
from websearch_lite.app.scheduler import Scheduler
from websearch_lite.facts.extractor import FactExtractor, load_schema
from websearch_lite.facts.llm_classifier import LocalLLMClassifier, build_prompt
from websearch_lite.storage import migration
from websearch_lite.storage.sqlite_store import Store

CFG = {"id": "gov_procurement", "label": "G", "schema_version": "procurement_v1",
       "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                       "base_url": "https://a.cn/", "role": "authoritative"},
       "authority_scope": [], "trust_weight": 1.0}


def _store():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
    store.register_domain(CFG, "x.json")
    return tmp, store


def _config(tmp: str) -> dict:
    return {"database": str(Path(tmp) / "t.db"), "temp_root": str(Path(tmp) / "temp"),
            "search_engine": "fts5", "tantivy_root": str(Path(tmp) / "idx"),
            "classifier": {"mode": "rule", "local_endpoint": "http://127.0.0.1:9/v1", "model": "none"},
            "p5": {"default_frequency": "daily", "max_retries": 2, "running_stale_minutes": 30},
            "consistency": {"mismatch_warn_threshold": 1, "rebuild_trigger_percent": 1.0}}


def test_daemon_round_no_due_tasks():
    tmp, store = _store()
    try:
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE domains SET enabled=1 WHERE domain_id=?", ("gov_procurement",))
            db.commit()
        result = run_once(_config(tmp.name), {}, store)
        assert result["due"] == 0
        assert result["consistency"]["mismatch"] == 0
    finally:
        tmp.cleanup()


def test_incremental_defers_not_due_tasks():
    tmp, store = _store()
    try:
        cfg = _config(tmp.name)
        store.enqueue_url("s1", "https://a.cn/1", "https://a.cn/1")
        store.enqueue_url("s1", "https://a.cn/2", "https://a.cn/2")
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE crawl_tasks SET next_run_at='2099-01-01T00:00:00+00:00'")
            db.commit()
        scheduler = Scheduler(store, cfg)
        assert scheduler.due_tasks() == []
        assert len(store.claim_crawl_tasks("s1", [], 10)) == 0
    finally:
        tmp.cleanup()


def test_llm_classifier_unavailable_falls_back_to_rule():
    tmp, store = _store()
    try:
        cfg = _config(tmp.name)
        cfg["classifier"]["mode"] = "local-llm"
        extractor = FactExtractor(store, "gov_procurement", config=cfg)
        assert extractor.llm is None
        assert extractor.llm_probe.get("available") is False
        result = extractor._classify("项目编号：X-1\n中标金额：10 万元", {})
        assert result["classifier"] == "rule"
        assert result["fields"]["award_amount"]["normalized"] == "100000.0"
    finally:
        tmp.cleanup()


def test_llm_prompt_only_lists_schema_fields():
    schema = load_schema("gov_procurement")
    prompt = build_prompt(schema, "文本")
    for spec in schema["facts"]:
        assert spec["predicate"] in prompt
    assert "不要编造" in prompt


def test_llm_rejects_hallucinated_value():
    tmp, store = _store()
    try:
        schema = load_schema("gov_procurement")
        classifier = LocalLLMClassifier(schema, _config(tmp.name))
        classifier._call = lambda text: [{"predicate": "project_code", "value": "NOT-IN-TEXT"}]
        result = classifier.classify("项目编号：X-1")
        assert result["fields"] == {}  # 值不在原文 → 丢弃
    finally:
        tmp.cleanup()


def test_restore_creates_pre_restore_backup():
    tmp, store = _store()
    try:
        first = migration.backup(store, backup_dir=str(Path(tmp.name) / "bk1"))
        result = migration.restore(store, first["backup_dir"], dry_run=False)
        assert result["restored"] is True
        assert Path(result["pre_restore_backup"]).exists()
    finally:
        tmp.cleanup()


def test_storage_io_probe_reports_writable():
    tmp, store = _store()
    try:
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE domains SET storage_path=? WHERE domain_id=?", (tmp.name, "gov_procurement"))
            db.commit()
        info = migration.check_storage_paths(store)
        assert info["database_writable"] is True
        assert info["offline_domains"] == []
        assert info["readonly_domains"] == []
    finally:
        tmp.cleanup()


def test_storage_reports_missing_domain_path():
    tmp, store = _store()
    try:
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE domains SET storage_path=? WHERE domain_id=?", (str(Path(tmp.name) / "gone"), "gov_procurement"))
            db.commit()
        info = migration.check_storage_paths(store)
        assert "gov_procurement" in info["offline_domains"]
    finally:
        tmp.cleanup()
