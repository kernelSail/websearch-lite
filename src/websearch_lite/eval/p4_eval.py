"""P4 评测：固定查询集 Recall@K / nDCG@K / 引用正确率。

优先使用文档级标注（eval/p4_relevance.json），缺失时回退到域级近似并标注 approximation=True。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from websearch_lite.paths import find_project_root
from websearch_lite.query.coordinator import QueryCoordinator

ROOT = find_project_root()
LABELS = ROOT / "eval" / "p4_queries.json"
RELEVANCE = ROOT / "eval" / "p4_relevance.json"


def default_labels() -> list[dict]:
    return [
        {"id": "p4_01", "query": "采购", "relevant_domains": ["gov_procurement"], "k": 5},
        {"id": "p4_02", "query": "中标", "relevant_domains": ["gov_procurement"], "k": 5},
        {"id": "p4_03", "query": "证券代码", "relevant_domains": ["listed_announcement"], "k": 5},
        {"id": "p4_04", "query": "公告", "relevant_domains": ["listed_announcement"], "k": 5},
        {"id": "p4_05", "query": "zzzz-不存在-xyz", "relevant_domains": [], "k": 5},
    ]


def load_labels() -> list[dict]:
    """优先文档级标注；结构统一为 {id, query, k, relevant_doc_ids}。"""
    if RELEVANCE.exists():
        return json.loads(RELEVANCE.read_text(encoding="utf-8"))["queries"]
    if LABELS.exists():
        legacy = json.loads(LABELS.read_text(encoding="utf-8"))
        return [{**item, "relevant_doc_ids": [], "domain_only": item.get("relevant_domains", [])}
                for item in legacy]
    LABELS.write_text(json.dumps(default_labels(), ensure_ascii=False, indent=2), encoding="utf-8")
    return default_labels()


def evaluate(coordinator: QueryCoordinator) -> dict:
    labels = load_labels()
    rows = []
    for item in labels:
        started = time.perf_counter()
        result = coordinator.search(item["query"], limit=item["k"])
        latency = int((time.perf_counter() - started) * 1000)
        hits = result["results"][: item["k"]]
        k = item["k"]
        relevant_docs = set(item.get("relevant_doc_ids") or [])
        domain_only = set(item.get("domain_only") or item.get("relevant_domains") or [])
        approximation = not relevant_docs and bool(domain_only)

        if relevant_docs:
            hit_ids = [str(h.get("doc_id") or "") for h in hits]
            gains = [1.0 if doc in relevant_docs else 0.0 for doc in hit_ids]
            found = len([g for g in gains if g])
            recall = found / len(relevant_docs)
            precision = found / max(1, len(hit_ids))
            dcg = sum(g / (1 + i) for i, g in enumerate(gains))
            ideal_count = min(len(relevant_docs), k)
            idcg = sum(1.0 / (1 + i) for i in range(ideal_count)) or 1.0
            ndcg = round(min(1.0, dcg / idcg), 4)
        elif approximation:
            # 域级近似：只能判断「是否命中相关域」
            recall = 1.0 if any(h.get("domain_id") in domain_only for h in hits) else 0.0
            precision = None
            ndcg = round(recall, 4)
        else:
            # 标注为「应无命中」
            recall, precision, ndcg = (1.0 if not hits else 0.0), None, (1.0 if not hits else 0.0)

        rows.append({
            "id": item["id"], "query": item["query"], "hits": len(hits),
            "recall_at_k": round(recall, 4),
            "precision_at_k": None if precision is None else round(precision, 4),
            "ndcg_at_k": ndcg,
            "approximation": approximation,
            "citations_valid": result["citations_valid"], "latency_ms": latency,
            "routed_domains": result["routed_domains"],
        })

    n = len(rows) or 1
    doc_level = [r for r in rows if not r["approximation"]]

    def mean(key: str, subset: list[dict]) -> float | None:
        values = [r[key] for r in subset if r[key] is not None]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "labels": str(RELEVANCE if RELEVANCE.exists() else LABELS),
        "total": len(rows),
        "doc_level_queries": len(doc_level),
        "recall_at_k": mean("recall_at_k", doc_level),
        "precision_at_k": mean("precision_at_k", doc_level),
        "ndcg_at_k": mean("ndcg_at_k", doc_level),
        "recall_at_k_all": mean("recall_at_k", rows),
        "citation_accuracy": round(sum(1 for r in rows if r["citations_valid"]) / n, 4),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / n, 2),
        "rows": rows,
    }
