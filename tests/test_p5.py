"""P5 测试：增量调度、条件请求复用、恢复、迁移、备份恢复、一致性。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.recovery import Recovery
from websearch_lite.app.scheduler import Scheduler
from websearch_lite.storage import migration
from websearch_lite.storage.consistency import check_consistency
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


def _config(tmp):
    return {"database": str(Path(tmp) / "t.db"), "temp_root": str(Path(tmp) / "temp"),
            "p5": {"default_frequency": "daily", "max_retries": 2, "running_stale_minutes": 30},
            "consistency": {"mismatch_warn_threshold": 1, "rebuild_trigger_percent": 1.0},
            "search_engine": "fts5"}


def test_scheduler_due_and_reschedule():
    tmp, store = _store()
    try:
        cfg = _config(tmp.name)
        store.enqueue_url("s1", "https://a.cn/1", "https://a.cn/1")
        scheduler = Scheduler(store, cfg)
        assert len(scheduler.due_tasks()) == 1
        tasks = scheduler.due_tasks()
        next_run = scheduler.schedule_next(tasks[0]["crawl_task_id"], "s1", succeeded=True)
        assert next_run is not None
        store.finish_crawl(tasks[0]["crawl_task_id"], "succeeded", http_status=200)
        assert scheduler.reschedule("s1") == 1
    finally:
        tmp.cleanup()


def test_conditional_fetch_304_reuses():
    tmp, store = _store()
    try:
        cfg = _config(tmp.name)
        store.enqueue_url("s1", "https://a.cn/1", "https://a.cn/1")
        scheduler = Scheduler(store, cfg)
        # 用假 fetcher 模拟 304，避免真实网络
        class FakeFetcher:
            def fetch(self, *a, **k):
                class R:
                    from_cache = True
                    error = None
                return R()
        scheduler.fetcher = FakeFetcher()
        task = scheduler.due_tasks()[0]
        out = scheduler.conditional_fetch(task, respect_robots=False)
        assert out["status"] == "not_modified" and out["reused"] is True
    finally:
        tmp.cleanup()


def test_recovery_stale_and_retry():
    tmp, store = _store()
    try:
        cfg = _config(tmp.name)
        store.enqueue_url("s1", "https://a.cn/1", "https://a.cn/1")
        tasks = store.next_crawl_tasks("s1", 1)  # 置为 running
        # 强制过期
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE crawl_tasks SET updated_at='2020-01-01T00:00:00+00:00'")
            db.commit()
        recovery = Recovery(store, cfg)
        out = recovery.recover_stale_running()
        assert out["crawl"] == 1
        # 重试预算耗尽 → failed + 复核
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("UPDATE crawl_tasks SET task_status='retry_wait', attempts=5")
            db.commit()
        retry = recovery.retry_waiting()
        assert retry["failed"] == 1 and retry["reviews"] == 1
        with __import__("contextlib").closing(store._connect()) as db:
            assert db.execute("SELECT task_status FROM crawl_tasks").fetchone()[0] == "failed"
    finally:
        tmp.cleanup()


def test_consume_pipeline_tasks():
    tmp, store = _store()
    try:
        text = "项目名称：X\n项目编号：P5-1\n中标金额：1 万元"
        ing = store.ingest(domain_id="gov_procurement", source_id="s1",
                           url="https://a.cn/1", canonical_url="https://a.cn/1",
                           title="t", text=text, published_at=None,
                           fetched_at="2026-11-06T00:00:00Z", http_status=200,
                           etag=None, last_modified=None, extraction_status="success",
                           metadata={}, doc_type="procurement", run_id="r")
        pending = store.stats()["pipeline_tasks"]
        out = Recovery(store, _config(tmp.name)).consume_pipeline_tasks()
        assert out["consumed"] == pending
        assert store.stats()["pipeline_tasks"] == pending  # 总数不变，只是状态变了
    finally:
        tmp.cleanup()


def test_migration_applies_once():
    tmp, store = _store()
    try:
        first = migration.migrate(store)
        assert "001_init" in first["applied"]
        second = migration.migrate(store)
        assert second["applied"] == []
    finally:
        tmp.cleanup()


def test_backup_and_restore_roundtrip():
    tmp, store = _store()
    try:
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("INSERT INTO domains VALUES (?,?,?,?,?,1,?,?)",
                       ("d1", "D1", "v1", "x", "p", "2026-11-06", "2026-11-06"))
            db.commit()
        backup_dir = Path(tmp.name) / "bk"
        out = migration.backup(store, backup_dir=str(backup_dir))
        assert out["files"] > 0
        check = migration.verify_backup(out["backup_dir"])
        assert check["valid"] is True
        dry = migration.restore(store, out["backup_dir"], dry_run=True)
        assert dry["dry_run"] is True and dry["check"]["valid"] is True
    finally:
        tmp.cleanup()


def test_consistency_check_reports_clean():
    tmp, store = _store()
    try:
        from websearch_lite.indexing import build_search_port
        cfg = _config(tmp.name)
        port = build_search_port(cfg, store)
        result = check_consistency(store, port, cfg)
        assert result["mismatch"] == 0
        assert result["warn"] is False
    finally:
        tmp.cleanup()
