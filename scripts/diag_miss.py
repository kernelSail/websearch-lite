"""诊断：为何某文档未命中指定查询。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import load_config
from websearch_lite.indexing.tantivy_port import TantivySearchPort
from websearch_lite.indexing.tokenizer import query_tokens, tokenize


def main() -> int:
    cfg = load_config()
    query = "中标公告"
    target = "idx_3f2f91ff21ad23eb"
    print("query tokens:", query_tokens(query))
    port = TantivySearchPort(cfg["tantivy_root"])
    hits = port.search(query, filters={"domain_id": "listed_announcement"}, limit=10)
    print("listed hits:", len(hits))
    for hit in hits:
        print("  ", hit["doc_id"], (hit.get("title") or "")[:40])

    db = sqlite3.connect(cfg["database"])
    row = db.execute("SELECT title, snippet FROM documents_index WHERE doc_id=?", (target,)).fetchone()
    if row:
        print("target title:", row[0])
        print("target title tokens:", tokenize(row[0] or ""))
        print("target snippet tokens:", tokenize((row[1] or "")[:200]))
    else:
        print("target not found in index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
