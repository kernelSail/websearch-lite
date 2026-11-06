"""P5 一致性监测与索引重建（V1.1 §11.5 / 评审决断 ⑦）。"""
from __future__ import annotations

from typing import Any

from ..common import now_iso, short_id
from ..indexing.tantivy_port import TantivySearchPort
from ..paths import find_project_root

ROOT = find_project_root()


def check_consistency(store, port, config: dict) -> dict:
    """SQLite 权威 vs 检索投影：缺失/版本不匹配/失败任务积压。"""
    base = store.consistency()
    active = store.stats().get("active_documents", 0)
    indexed = store.stats().get("indexed_documents", 0)
    threshold = int(config.get("consistency", {}).get("mismatch_warn_threshold", 1))
    rebuild_percent = float(config.get("consistency", {}).get("rebuild_trigger_percent", 1.0))
    mismatch = len(base["missing_index"]) + len(base["version_mismatch"])
    with __import__("contextlib").closing(store._connect()) as db:
        failed_tasks = db.execute(
            "SELECT COUNT(*) FROM index_tasks WHERE task_status IN ('failed','retry_wait')"
        ).fetchone()[0]
    percent = (mismatch / max(1, active)) * 100.0
    return {
        "missing_index": base["missing_index"],
        "version_mismatch": base["version_mismatch"],
        "mismatch": mismatch,
        "active_documents": active,
        "indexed_documents": indexed,
        "failed_index_tasks": failed_tasks,
        "percent": round(percent, 4),
        "warn": mismatch >= threshold,
        "rebuild_required": percent > rebuild_percent or mismatch > 0,
        "engine": getattr(port, "name", type(port).__name__),
    }


def rebuild_index(store, config: dict) -> dict:
    """从 SQLite 全量重建 Tantivy 投影，并抽样核验。"""
    port = TantivySearchPort(config.get("tantivy_root", str(ROOT / "domains_index")))
    docs = store.all_index_documents()
    port.rebuild(docs)
    stats = port.stats()
    sample = docs[:3]
    verified = 0
    for doc in sample:
        hits = port.search(str(doc.get("title") or "")[:6],
                           filters={"domain_id": doc.get("domain_id")}, limit=5)
        if hits:
            verified += 1
    # 记录重建任务（index_tasks 的 domain_id/document_id 都有外键，用真实值或跳过）
    sample_ids = [(str(d.get("domain_id")), str(d.get("document_id")))
                  for d in sample if d.get("domain_id") and d.get("document_id")]
    if sample_ids:
        domain_id, document_id = sample_ids[0]
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute(
                """INSERT INTO index_tasks(index_task_id,domain_id,document_id,document_version_id,
                     operation,task_status,idempotency_key,attempts,next_run_at,last_error,created_at,updated_at)
                   VALUES (?,?,?,?,?,'succeeded',?,?,?,?,?,?)""",
                (short_id("idxrun", now_iso()), domain_id, document_id, None, "upsert",
                 short_id("idem", now_iso()), 1, None, None, now_iso(), now_iso()),
            )
            db.commit()
    return {"engine": stats, "documents_rebuilt": len(docs), "sample_verified": verified,
            "sample_size": len(sample)}
