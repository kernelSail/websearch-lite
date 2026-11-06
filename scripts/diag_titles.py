"""诊断：标题为空的文档来源与元数据。"""
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
    rows = db.execute("SELECT * FROM documents_index WHERE title='' OR title IS NULL").fetchall()
    print("empty-title index rows:", len(rows))
    for row in rows:
        print(json.dumps({"doc_id": row["doc_id"], "url": row["url"],
                          "snippet": (row["snippet"] or "")[:100]}, ensure_ascii=False))
    versions = db.execute(
        "SELECT document_version_id,document_id,title,metadata_json FROM document_versions WHERE title='' OR title IS NULL"
    ).fetchall()
    print("empty-title versions:", len(versions))
    for row in versions:
        print(json.dumps({"dv": row["document_version_id"], "metadata": (row["metadata_json"] or "")[:300]},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
