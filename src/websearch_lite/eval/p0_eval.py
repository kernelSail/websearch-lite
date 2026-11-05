"""P0 固定查询集评测：无标注集时用人工核对命中数，不假装算 Recall@K。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
QUERY_SET = ROOT / "eval" / "queries.json"


def load_query_set() -> list[dict]:
    if not QUERY_SET.exists():
        default = [
            {"id": "q01", "query": "中标公告", "domain": "gov_procurement", "expect": "any"},
            {"id": "q02", "query": "采购", "domain": "gov_procurement", "expect": "any"},
            {"id": "q03", "query": "公告", "domain": "listed_announcement", "expect": "any"},
            {"id": "q04", "query": "证券", "domain": "listed_announcement", "expect": "any"},
            {"id": "q05", "query": "zzzz-不存在的关键词-xyz", "domain": None, "expect": "zero"},
            {"id": "q06", "query": "成交", "domain": "gov_procurement", "expect": "any"},
            {"id": "q07", "query": "医院", "domain": "gov_procurement", "expect": "any"},
        ]
        QUERY_SET.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    return json.loads(QUERY_SET.read_text(encoding="utf-8"))


def run_eval(store) -> dict:
    rows = load_query_set()
    results = []
    for item in rows:
        hits = store.search(item["query"], domain_id=item.get("domain"), limit=20)
        count = len(hits)
        if item.get("expect") == "zero":
            passed = count == 0
        else:
            passed = count > 0
        results.append({
            "id": item["id"], "query": item["query"], "domain": item.get("domain"),
            "hits": count, "expect": item.get("expect"), "passed": passed,
            "sample_titles": [h["title"][:40] for h in hits[:3]],
        })
    return {
        "query_set": str(QUERY_SET),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "note": "P0 无人工标注集，指标为固定查询集命中数；Recall@K/Precision@K 待 P2 标注集完成后启用。",
    }
