"""诊断：抽取失败原因与空标题文档。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import load_config


def main() -> int:
    config = load_config()
    db = sqlite3.connect(config["database"])
    db.row_factory = sqlite3.Row
    print("docs:", db.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    print("versions:", db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0])
    print("index:", db.execute("SELECT COUNT(*) FROM documents_index").fetchone()[0])
    print("facts:", db.execute("SELECT COUNT(*) FROM facts").fetchone()[0])

    rows = db.execute("SELECT crawl_task_id,last_error,url FROM crawl_tasks WHERE last_error IS NOT NULL").fetchall()
    print("tasks with errors:", len(rows))
    for row in rows[:5]:
        print(json.dumps({"task": row["crawl_task_id"], "url": (row["url"] or "")[:70],
                          "error": (row["last_error"] or "")[:400]}, ensure_ascii=False))

    empty = db.execute("SELECT COUNT(*) FROM documents_index WHERE title='' OR title IS NULL").fetchone()[0]
    print("empty-title docs:", empty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
