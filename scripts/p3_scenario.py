"""临时场景：双源与冲突裁决的人工验收脚本（不入库，不用 pytest）。"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.storage.sqlite_store import Store
from websearch_lite.verification.verifier import Verifier

CFG = {"id": "gov_procurement", "label": "G", "schema_version": "procurement_v1",
       "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                       "base_url": "https://a.cn/", "role": "authoritative"},
       "authority_scope": [], "trust_weight": 1.0}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db", ROOT / "migrations")
        store.register_domain(CFG, "x")
        with closing(store._connect()) as db:
            db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("s2", "gov_procurement", "S2", "https://b.cn/", "corroborating",
                        "[]", 0.8, 1, 1.0, 1, 1, None, None, 0, "2026-11-06", "2026-11-06"))
            db.commit()

        text = "项目名称：某某项目\n项目编号：P3-DEMO-001\n中标金额：100 万元"
        a = store.ingest(domain_id="gov_procurement", source_id="s1", url="https://a.cn/1",
                         canonical_url="https://a.cn/1", title="公告A", text=text,
                         published_at=None, fetched_at="2026-11-01T00:00:00Z", http_status=200,
                         etag=None, last_modified=None, extraction_status="success",
                         metadata={}, doc_type="procurement", run_id="r")
        b = store.ingest(domain_id="gov_procurement", source_id="s2", url="https://b.cn/1",
                         canonical_url="https://b.cn/1", title="公告B", text=text,
                         published_at=None, fetched_at="2026-11-02T00:00:00Z", http_status=200,
                         etag=None, last_modified=None, extraction_status="success",
                         metadata={}, doc_type="procurement", run_id="r")

        with closing(store._connect()) as db:
            db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
                       ("ent_1", "gov_procurement", None, "project_code:P3-DEMO-001",
                        "某某项目", "organization", "2026-11-06", "2026-11-06"))
            db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
                       ("fact_1", "gov_procurement", "ent_1", "award_amount", "", "2026-11-06", "2026-11-06"))
            db.execute("""INSERT INTO fact_versions
                          (fact_version_id,fact_id,version_no,value_json,normalized_value,
                           verification_status,schema_version,created_at)
                          VALUES (?,?,?,?,?,?,?,?)""",
                       ("fv_1", "fact_1", 1, "{}", "1000000.0", "unverified",
                        "procurement_v1", "2026-11-06"))
            for i, dv in enumerate([a["document_version_id"], b["document_version_id"]], 1):
                db.execute("INSERT INTO fact_evidences VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (f"ev_{i}", "fv_1", dv, "s1" if i == 1 else "s2", 0, 0, 20,
                            "中标金额：100 万元", "supports", f"h{i}", "2026-11-06"))
            db.commit()

        verifier = Verifier(store)
        result = verifier.verify("fv_1")
        print("verify:", json.dumps(result, ensure_ascii=False))
        print("relationships:", store.source_relationships_count())
        print("counts:", json.dumps(store.verification_counts(), ensure_ascii=False))

        # 制造第二值 → conflicting + 冲突快照 + 人工裁决
        with closing(store._connect()) as db:
            db.execute("""INSERT INTO fact_versions
                          (fact_version_id,fact_id,version_no,value_json,normalized_value,
                           verification_status,schema_version,created_at)
                          VALUES (?,?,?,?,?,?,?,?)""",
                       ("fv_2", "fact_1", 2, "{}", "2000000.0", "unverified",
                        "procurement_v1", "2026-11-06"))
            db.execute("INSERT INTO fact_evidences VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       ("ev_conflict_2", "fv_2", b["document_version_id"], "s2", 0, 0, 20,
                        "中标金额：200 万元", "supports", "h_conflict", "2026-11-06"))
            db.commit()
        verifier2 = Verifier(store)
        print("verify_all:", json.dumps(verifier2.verify_all(), ensure_ascii=False))
        conflicts = store.list_conflicts()
        print("conflicts:", len(conflicts), "reviews:", len(store.list_reviews()))
        if conflicts:
            resolved = verifier2.resolve_conflict(conflicts[0]["conflict_id"], "fv_2",
                                                  reason="authoritative source correction")
            print("resolution:", json.dumps(resolved, ensure_ascii=False))
            print("after:", json.dumps(store.verification_counts(), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
