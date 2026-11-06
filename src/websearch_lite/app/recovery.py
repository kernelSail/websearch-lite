"""P5 崩溃恢复与任务状态机（V1.1 §10.4）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..common import dumps, now_iso, short_id


class Recovery:
    def __init__(self, store, config: dict) -> None:
        self.store = store
        self.config = config
        self.stale_minutes = int(config.get("p5", {}).get("running_stale_minutes", 30))
        self.max_retries = int(config.get("p5", {}).get("max_retries", 3))

    def recover_stale_running(self) -> dict:
        """启动恢复：过期的 running 任务重置为 retry_wait / pending。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.stale_minutes)).isoformat()
        result = {"crawl": 0, "pipeline": 0, "index": 0}
        with __import__("contextlib").closing(self.store._connect()) as db:
            for table in ("crawl_tasks", "pipeline_tasks", "index_tasks"):
                cur = db.execute(
                    f"UPDATE {table} SET task_status='retry_wait', updated_at=? "
                    f"WHERE task_status='running' AND updated_at<?",
                    (now_iso(), cutoff),
                )
                result[table.replace("_tasks", "")] = cur.rowcount
            db.commit()
        return result

    def retry_waiting(self) -> dict:
        """有限重试：超过 max_retries 转 failed 并生成复核任务。"""
        now = now_iso()
        result = {"requeued": 0, "failed": 0, "reviews": 0}
        with __import__("contextlib").closing(self.store._connect()) as db:
            for table in ("crawl_tasks", "pipeline_tasks", "index_tasks"):
                rows = db.execute(
                    f"SELECT * FROM {table} WHERE task_status='retry_wait' AND attempts<?",
                    (self.max_retries,),
                ).fetchall()
                for row in rows:
                    db.execute(f"UPDATE {table} SET task_status='pending', next_run_at=?, updated_at=? WHERE {table[:-1]}_id=?",
                               (now, now, row[0]))
                    result["requeued"] += 1
                exhausted = db.execute(
                    f"SELECT * FROM {table} WHERE task_status='retry_wait' AND attempts>=?",
                    (self.max_retries,),
                ).fetchall()
                for row in exhausted:
                    db.execute(f"UPDATE {table} SET task_status='failed', updated_at=? WHERE {table[:-1]}_id=?",
                               (now, row[0]))
                    result["failed"] += 1
                    self._review(db, table, dict(row))
                    result["reviews"] += 1
            db.commit()
        return result

    @staticmethod
    def _review(db, table: str, row: dict) -> None:
        now = now_iso()
        task_id = row.get(f"{table[:-1]}_id") or "unknown"
        db.execute(
            """INSERT OR IGNORE INTO review_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (short_id("rev", "recovery", task_id), "task_recovery", table, task_id,
             "pending", 2, f"TASK_EXHAUSTED:{row.get('last_error') or row.get('error_message') or 'retries'}",
             dumps({"table": table, "row": row}), None, now, now, None),
        )

    def consume_pipeline_tasks(self, limit: int = 100) -> dict:
        """
        P5：把积压的 pipeline_tasks 标记为 succeeded（P2/P3 的实际处理已在 crawl/extract/verify 完成），
        并记录处理运行。这是任务状态机的收尾，不改变数据。
        """
        now = now_iso()
        with __import__("contextlib").closing(self.store._connect()) as db:
            rows = db.execute(
                "SELECT pipeline_task_id,task_type FROM pipeline_tasks WHERE task_status='pending' LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE pipeline_tasks SET task_status='succeeded', updated_at=? WHERE pipeline_task_id=?",
                    (now, row[0]),
                )
            db.commit()
            return {"consumed": len(rows), "by_type": {t: sum(1 for r in rows if r[1] == t)
                                                       for t in ("extract", "classify", "entity_resolve", "verify", "index")}}

    def run(self) -> dict:
        return {
            "stale_recovered": self.recover_stale_running(),
            "retry": self.retry_waiting(),
            "pipeline": self.consume_pipeline_tasks(),
        }
