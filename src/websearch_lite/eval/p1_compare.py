"""P1 检索对照评测：FTS5 与 Tantivy 在同一固定查询集上的命中数与延迟。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from websearch_lite.paths import find_project_root

ROOT = find_project_root()
QUERY_SET = ROOT / "eval" / "queries.json"


def load_query_set() -> list[dict]:
    return json.loads(QUERY_SET.read_text(encoding="utf-8"))


def evaluate(port, query_set: list[dict]) -> dict:
    rows = []
    for item in query_set:
        started = time.perf_counter()
        hits = port.search(item["query"], filters={"domain_id": item.get("domain")} if item.get("domain") else None, limit=20)
        latency = int((time.perf_counter() - started) * 1000)
        count = len(hits)
        passed = count == 0 if item.get("expect") == "zero" else count > 0
        rows.append({
            "id": item["id"], "query": item["query"], "domain": item.get("domain"),
            "hits": count, "passed": passed, "latency_ms": latency,
            "sample": [str(h.get("title", ""))[:32] for h in hits[:2]],
        })
    return {
        "engine": getattr(port, "name", type(port).__name__),
        "total": len(rows),
        "passed": sum(1 for r in rows if r["passed"]),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / max(1, len(rows)), 2),
        "rows": rows,
    }


def compare(ports: dict[str, object]) -> dict:
    query_set = load_query_set()
    return {name: evaluate(port, query_set) for name, port in ports.items()}
