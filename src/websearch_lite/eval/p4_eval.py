"""P4 评测：固定查询集 Recall@K / nDCG@K / 引用正确率。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from websearch_lite.paths import find_project_root
from websearch_lite.query.coordinator import QueryCoordinator

ROOT = find_project_root()
LABELS = ROOT / "eval" / "p4_queries.json"


def default_labels() -> list[dict]:
    return [
        {"id": "p4_01", "query": "采购", "relevant_domains": ["gov_procurement"], "k": 5},
        {"id": "p4_02", "query": "中标", "relevant_domains": ["gov_procurement"], "k": 5},
        {"id": "p4_03", "query": "证券代码", "relevant_domains": ["listed_announcement"], "k": 5},
        {"id": "p4_04", "query": "公告", "relevant_domains": ["listed_announcement"], "k": 5},
        {"id": "p4_05", "query": "zzzz-不存在-xyz", "relevant_domains": [], "k": 5},
    ]


def load_labels() -> list[dict]:
    if not LABELS.exists():
        LABELS.write_text(json.dumps(default_labels(), ensure_ascii=False, indent=2), encoding="utf-8")
        return default_labels()
    return json.loads(LABELS.read_text(encoding="utf-8"))


def evaluate(coordinator: QueryCoordinator) -> dict:
    labels = load_labels()
    rows = []
    for item in labels:
        started = time.perf_counter()
        result = coordinator.search(item["query"], limit=item["k"])
        latency = int((time.perf_counter() - started) * 1000)
        hits = result["results"]
        relevant = set(item["relevant_domains"])
        k = item["k"]
        # Recall@K：相关域是否至少命中一条（无标注池时的可计算近似）
        recall = 1.0 if relevant and any(h.get("domain_id") in relevant for h in hits[:k]) else (
            0.0 if relevant else 1.0)
        # nDCG@K：二元增益，理想排序为「前 min(#相关命中, K) 位全是相关」
        gains = [1.0 if h.get("domain_id") in relevant else 0.0 for h in hits[:k]]
        dcg = sum(gain / (1 + i) for i, gain in enumerate(gains))
        ideal_count = min(sum(1 for g in gains if g), k)
        ideal = sum(1.0 / (1 + i) for i in range(ideal_count)) or 1.0
        ndcg = round(min(1.0, dcg / ideal), 4)
        rows.append({
            "id": item["id"], "query": item["query"], "hits": len(hits),
            "recall_at_k": round(recall, 4), "ndcg_at_k": ndcg,
            "citations_valid": result["citations_valid"], "latency_ms": latency,
            "routed_domains": result["routed_domains"],
        })
    n = len(rows) or 1
    return {
        "labels": str(LABELS),
        "total": len(rows),
        "recall_at_k": round(sum(r["recall_at_k"] for r in rows) / n, 4),
        "ndcg_at_k": round(sum(r["ndcg_at_k"] for r in rows) / n, 4),
        "citation_accuracy": round(sum(1 for r in rows if r["citations_valid"]) / n, 4),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / n, 2),
        "rows": rows,
        "note": "Recall@K 为域级命中近似（无文档级标注池），P2 标注集扩展后替换为真实相关性判定。",
    }
