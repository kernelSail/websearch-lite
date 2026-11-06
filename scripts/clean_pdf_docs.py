"""清理：删除误入库的 PDF 二进制正文文档（snippet 以 %PDF- 开头），按外键顺序删除。"""
from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import load_config, make_store


def main() -> int:
    config = load_config()
    store = make_store(config)
    with closing(store._connect()) as db:
        bad = [r[0] for r in db.execute(
            "SELECT document_id FROM documents_index WHERE snippet LIKE '%PDF-%'"
        ).fetchall()]
        print("candidate bad docs:", len(bad))
        for doc_id in bad:
            versions = [r[0] for r in db.execute(
                "SELECT document_version_id FROM document_versions WHERE document_id=?", (doc_id,)
            ).fetchall()]
            for version_id in versions:
                fv_ids = [r[0] for r in db.execute(
                    "SELECT DISTINCT fact_version_id FROM fact_evidences WHERE document_version_id=?",
                    (version_id,)
                ).fetchall()]
                db.execute("DELETE FROM fact_evidences WHERE document_version_id=?", (version_id,))
                db.execute("DELETE FROM raw_fact_candidates WHERE document_version_id=?", (version_id,))
                for fv_id in fv_ids:
                    fact_rows = db.execute("SELECT fact_id FROM fact_versions WHERE fact_version_id=?",
                                           (fv_id,)).fetchall()
                    db.execute("DELETE FROM fact_versions WHERE fact_version_id=?", (fv_id,))
                    for fact in fact_rows:
                        remaining = db.execute("SELECT COUNT(*) FROM fact_versions WHERE fact_id=?",
                                               (fact[0],)).fetchone()[0]
                        if remaining == 0:
                            db.execute("DELETE FROM facts WHERE fact_id=?", (fact[0],))
                db.execute("DELETE FROM pipeline_tasks WHERE document_version_id=?", (version_id,))
                db.execute("DELETE FROM crawl_tasks WHERE url IN "
                           "(SELECT url FROM documents WHERE document_id=?)", (doc_id,))
                db.execute("DELETE FROM document_versions WHERE document_version_id=?", (version_id,))
            db.execute("DELETE FROM documents_index WHERE document_id=?", (doc_id,))
            db.execute("DELETE FROM documents WHERE document_id=?", (doc_id,))
        db.commit()
        print("after: docs", db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
              "index", db.execute("SELECT COUNT(*) FROM documents_index").fetchone()[0],
              "versions", db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0],
              "empty titles", db.execute("SELECT COUNT(*) FROM documents_index WHERE title=''").fetchone()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
