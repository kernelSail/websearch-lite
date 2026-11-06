"""P5 增量调度：按 update_frequency 排期、ETag/Last-Modified 复用、幂等重跑。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..common import now_iso
from ..crawler.fetcher import Fetcher

FREQUENCY_SECONDS = {"hourly": 3600, "daily": 86400, "weekly": 604800, "monthly": 2592000}


class Scheduler:
    def __init__(self, store, config: dict) -> None:
        self.store = store
        self.config = config
        self.fetcher = Fetcher(config)

    def due_tasks(self, domain_id: str | None = None) -> list[dict]:
        """到期的 crawl 任务：pending / retry_wait 且 next_run_at 已过（或为空）。"""
        now = now_iso()
        with __import__("contextlib").closing(self.store._connect()) as db:
            clause = " AND d.domain_id=?" if domain_id else ""
            params: list = [now] + ([domain_id] if domain_id else [])
            return [dict(r) for r in db.execute(
                """SELECT c.* FROM crawl_tasks c JOIN sources s ON s.source_id=c.source_id
                   JOIN domains d ON d.domain_id=s.domain_id
                   WHERE c.task_status IN ('pending','retry_wait')
                     AND (c.next_run_at IS NULL OR c.next_run_at<=?)""" + clause +
                " ORDER BY c.priority DESC, c.discovered_at ASC", params
            ).fetchall()]

    def schedule_next(self, task_id: str, source_id: str, *, succeeded: bool) -> str | None:
        """成功后按域的 update_frequency 排下一次；失败按指数退避。"""
        with __import__("contextlib").closing(self.store._connect()) as db:
            src = db.execute(
                """SELECT d.domain_id FROM sources s JOIN domains d ON d.domain_id=s.domain_id
                   WHERE s.source_id=?""", (source_id,)
            ).fetchone()
            freq = self.config.get("p5", {}).get("default_frequency", "daily")
            seconds = FREQUENCY_SECONDS.get(freq, 86400)
            attempts = db.execute("SELECT attempts FROM crawl_tasks WHERE crawl_task_id=?", (task_id,)).fetchone()
            attempt = attempts[0] if attempts else 0
            delay = seconds if succeeded else min(3600 * (2 ** min(attempt, 4)), 86400)
            next_run = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            db.execute("UPDATE crawl_tasks SET next_run_at=?, updated_at=? WHERE crawl_task_id=?",
                       (next_run, now_iso(), task_id))
            db.commit()
            return next_run

    def conditional_fetch(self, task: dict, *, respect_robots: bool = True) -> dict:
        """
        条件请求：ETag/Last-Modified 命中 304 → 复用当前版本，不重跑抽取/归类/验证。
        返回 {status, fetch_result, reused}。
        """
        result = self.fetcher.fetch(
            task["url"], etag=task["etag"], last_modified=task["last_modified"],
            rps=float(self.config.get("p5", {}).get("rate_limit_rps", 1.0)),
            respect_robots=respect_robots, base_url=task["url"],
        )
        if result.from_cache:
            return {"status": "not_modified", "fetch_result": result, "reused": True}
        return {"status": "modified" if not result.error else "failed",
                "fetch_result": result, "reused": False}

    def stats(self) -> dict:
        with __import__("contextlib").closing(self.store._connect()) as db:
            return {
                "due": len(self.due_tasks()),
                "by_status": {r[0]: r[1] for r in db.execute(
                    "SELECT task_status,COUNT(*) FROM crawl_tasks GROUP BY task_status")},
                "scheduled_ahead": db.execute(
                    "SELECT COUNT(*) FROM crawl_tasks WHERE next_run_at>?", (now_iso(),)
                ).fetchone()[0],
            }

    def reschedule(self, source_id: str) -> int:
        """把该来源已完成/失败/待重试的任务重新排为 pending（保留 ETag/Last-Modified）。"""
        now = now_iso()
        with __import__("contextlib").closing(self.store._connect()) as db:
            cur = db.execute(
                """UPDATE crawl_tasks SET task_status='pending', next_run_at=NULL, updated_at=?
                   WHERE source_id=? AND task_status IN ('succeeded','retry_wait','failed','skipped')""",
                (now, source_id),
            )
            db.commit()
            return cur.rowcount
