"""中断恢复演练：模拟进程被杀后 running 任务的重置与重排。"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import load_config, make_store
from websearch_lite.app.recovery import Recovery
from websearch_lite.app.scheduler import Scheduler


def main() -> int:
    config = load_config()
    store = make_store(config)
    db_path = store.path

    with closing(sqlite3.connect(db_path)) as db:
        ids = [r[0] for r in db.execute("SELECT crawl_task_id FROM crawl_tasks LIMIT 2")]
        for task_id in ids:
            db.execute(
                "UPDATE crawl_tasks SET task_status='running', updated_at='2020-01-01T00:00:00+00:00' WHERE crawl_task_id=?",
                (task_id,),
            )
        db.commit()
    print(json.dumps({"simulated_killed": ids}, ensure_ascii=False))

    with closing(sqlite3.connect(db_path)) as db:
        before = dict(db.execute("SELECT task_status,COUNT(*) FROM crawl_tasks GROUP BY task_status"))

    recovery = Recovery(store, config)
    out = recovery.run()

    with closing(sqlite3.connect(db_path)) as db:
        after = dict(db.execute("SELECT task_status,COUNT(*) FROM crawl_tasks GROUP BY task_status"))
        retry_rows = db.execute(
            "SELECT crawl_task_id,task_status,attempts FROM crawl_tasks WHERE crawl_task_id IN (?,?)",
            ids,
        ).fetchall()

    print(json.dumps({
        "recovery": out,
        "before": before,
        "after": after,
        "recovered_tasks": [list(r) for r in retry_rows],
        "due_now": len(Scheduler(store, config).due_tasks()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
