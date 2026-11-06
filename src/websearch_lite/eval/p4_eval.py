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


def _metrics(hit_ids: list[str], relevant: set[str], k: int) -> dict:
    """R@K / P@K / nDCG@K / MRR，并给出 K 截断归一化召回。"""
    top = hit_ids[:k]
    gains = [1.0 if doc in relevant else 0.0 for doc in top]
    found = int(sum(gains))
    recall = found / len(relevant)
    precision = found / max(1, len(top))
    dcg = sum(g / (1 + i) for i, g in enumerate(gains))
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / (1 + i) for i in range(ideal_count)) or 1.0
    ndcg = round(min(1.0, dcg / idcg), 4)
    # 首个相关位置 → MRR
    mrr = 0.0
    for i, gain in enumerate(gains):
        if gain:
            mrr = round(1.0 / (i + 1), 4)
            break
    # K < 相关文档数时 Recall 上限 < 1，做上限归一化才能看出真实缺口
    ceiling = min(1.0, k / len(relevant)) if relevant else 1.0
    return {
        "recall": round(recall, 4),
        "recall_normalized": round(recall / ceiling, 4) if ceiling else 0.0,
        "precision": round(precision, 4),
        "ndcg": ndcg,
        "mrr": mrr,
        "k_truncated": len(relevant) > k,
    }


def evaluate(coordinator: QueryCoordinator) -> dict:
    labels = load_labels()
    rows = []
    for item in labels:
        k = item["k"]
        max_k = max(k, 10)  # 一次检索跑大 K，同时评估 R@K 与 R@10（识别 K 截断影响）
        started = time.perf_counter()
        result = coordinator.search(item["query"], limit=max_k)
        latency = int((time.perf_counter() - started) * 1000)
        hit_ids = [str(h.get("doc_id") or "") for h in result["results"]]
        relevant_docs = set(item.get("relevant_doc_ids") or [])
        domain_only = set(item.get("domain_only") or item.get("relevant_domains") or [])
        approximation = not relevant_docs and bool(domain_only)

        if relevant_docs:
            metrics = _metrics(hit_ids, relevant_docs, k)
            metrics10 = _metrics(hit_ids, relevant_docs, max_k)
        elif approximation:
            hit = any(h.get("domain_id") in domain_only for h in result["results"][:k])
            metrics = {"recall": 1.0 if hit else 0.0, "recall_normalized": 1.0 if hit else 0.0,
                       "precision": None, "ndcg": 1.0 if hit else 0.0, "mrr": 1.0 if hit else 0.0,
                       "k_truncated": False}
            metrics10 = dict(metrics)
        else:
            # 标注为「应无命中」：有多余结果即失败
            clean = not result["results"]
            metrics = {"recall": 1.0 if clean else 0.0, "recall_normalized": 1.0 if clean else 0.0,
                       "precision": None, "ndcg": 1.0 if clean else 0.0, "mrr": 1.0 if clean else 0.0,
                       "k_truncated": False}
            metrics10 = dict(metrics)

        rows.append({
            "id": item["id"], "query": item["query"], "hits": len(hit_ids), "k": k,
            "recall_at_k": metrics["recall"],
            "recall_at_k_normalized": metrics["recall_normalized"],
            "precision_at_k": metrics["precision"],
            "ndcg_at_k": metrics["ndcg"],
            "mrr": metrics["mrr"],
            "recall_at_10": metrics10["recall"],
            "k_truncated": metrics["k_truncated"],
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
        "k_truncated_queries": sum(1 for r in rows if r["k_truncated"]),
        "recall_at_k": mean("recall_at_k", doc_level),
        "recall_at_k_normalized": mean("recall_at_k_normalized", doc_level),
        "precision_at_k": mean("precision_at_k", doc_level),
        "ndcg_at_k": mean("ndcg_at_k", doc_level),
        "mrr": mean("mrr", doc_level),
        "recall_at_10": mean("recall_at_10", doc_level),
        "recall_at_k_all": mean("recall_at_k", rows),
        "citation_accuracy": round(sum(1 for r in rows if r["citations_valid"]) / n, 4),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / n, 2),
        "rows": rows,
    }
