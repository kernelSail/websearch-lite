"""P4 统一查询层：域路由、结构化过滤、跨域归一化合并、证据约束答案。"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..common import dumps, hamming, now_iso, short_id, simhash
from ..indexing import build_search_port


class QueryCoordinator:
    RRF_K = 60  # Reciprocal Rank Fusion 平滑常数

    def __init__(self, store, config: dict) -> None:
        self.store = store
        self.config = config
        self.port = build_search_port(config, store)
        self.extra_ports = self._build_extra_ports(config, store)

    @staticmethod
    def _build_extra_ports(config: dict, store) -> list:
        """hybrid 模式：主引擎（Tantivy 分词）之外补 FTS5 trigram 做 RRF 融合。"""
        mode = str(config.get("search_engine", "fts5"))
        if mode != "hybrid":
            return []
        try:
            from ..indexing.fts5_port import Fts5SearchPort
            return [Fts5SearchPort(store)]
        except Exception:
            return []

    # ---------- 域路由 ----------
    def route(self, query: str, filters: dict | None = None) -> list[str]:
        filters = filters or {}
        if filters.get("domain_id"):
            return [filters["domain_id"]]
        with __import__("contextlib").closing(self.store._connect()) as db:
            domains = [r[0] for r in db.execute("SELECT domain_id FROM domains WHERE enabled=1")]
        # 关键词只用于「排序优先」，不做硬过滤：同一查询可能同时命中不同域
        # （如「中标公告」在政府采购域是结果公告、在上市公司域是重大合同中标公告）。
        text = query.lower()
        hints = {
            "gov_procurement": ("采购", "中标", "招标", "成交", "预算", "采购人"),
            "listed_announcement": ("公告", "证券", "年报", "报告", "上市公司", "披露", "股份"),
        }
        priority = [d for d, keywords in hints.items()
                    if d in domains and any(k in text for k in keywords)]
        rest = [d for d in domains if d not in priority]
        return priority + rest

    # ---------- 检索 ----------
    def search(self, query: str, *, filters: dict | None = None, limit: int = 20) -> dict:
        filters = filters or {}
        domains = self.route(query, filters)
        # 多召回：原始查询 + 去尾缀变体，缓解「中标公告」只匹配「招标公告」的片段偏差
        variants = [query] + [v for v in [self._strip_generic_suffix(query)] if v and v != query]
        raw: list[dict] = []
        rank_lists: list[tuple[list[str], float]] = []

        def collect(port, variant: str, domain_id: str, weight: float = 1.0) -> None:
            # 内部用更大候选池，避免融合前就把尾部相关内容截掉；最终仍按 limit 返回
            pool = max(limit * 3, 20)
            try:
                hits = port.search(variant, filters={**filters, "domain_id": domain_id}, limit=pool)
            except Exception:
                return
            for rank, hit in enumerate(hits):
                seen = {r.get("doc_id") for r in raw}
                if hit.get("doc_id") in seen:
                    continue
                item = dict(hit)
                item["domain_id"] = domain_id
                # 域内归一化：不同域 BM25 原始分不可直接比较（V1.1 §12.3）
                item["rank_normalized"] = round(1.0 - rank / max(1, len(hits)), 4)
                item["raw_score"] = float(item.get("score") or item.get("relevance") or 0.0)
                raw.append(item)
            rank_lists.append(([str(h.get("doc_id")) for h in hits], weight))

        # 主引擎权重高于补充引擎：分词引擎（tantivy）精确，trigram（fts5）召回宽但噪声多
        for domain_id in domains:
            for variant in variants:
                collect(self.port, variant, domain_id, 1.0)
                for port in self.extra_ports:
                    collect(port, variant, domain_id, 0.5)

        # 加权 RRF 融合：Σ weight/(k+rank)，归一化到 [0,1]
        rrf: dict[str, float] = {}
        for ids, weight in rank_lists:
            for rank, doc_id in enumerate(ids):
                rrf[doc_id] = rrf.get(doc_id, 0.0) + weight / (self.RRF_K + rank + 1)
        if rrf:
            top = max(rrf.values()) or 1.0
            for item in raw:
                item["rrf_score"] = round(rrf.get(str(item.get("doc_id")), 0.0) / top, 4)

        # 结构化过滤
        raw = self._apply_filters(raw, filters)
        # 全局去重（URL + 内容近似）
        raw = self._dedup(raw)
        # 统一重排：归一化分 + 查询词覆盖 + 权威权重 + 新近度
        raw = self._rerank(raw, filters, query)
        # 事实/证据约束
        self._attach_facts(raw, filters)

        return {
            "query": query,
            "routed_domains": domains,
            "results": raw[:limit],
            "answer": self.render_answer(query, raw[:limit]),
            "citations_valid": self._validate_citations(raw[:limit]),
        }

    def _apply_filters(self, rows: list[dict], filters: dict) -> list[dict]:
        def keep(row: dict) -> bool:
            if filters.get("source_id") and row.get("source_id") != filters["source_id"]:
                return False
            if filters.get("title_contains"):
                if filters["title_contains"] not in (row.get("title") or ""):
                    return False
            since = filters.get("since")
            if since and str(row.get("fetched_at") or "") < str(since):
                return False
            until = filters.get("until")
            if until and str(row.get("fetched_at") or "") > str(until):
                return False
            return True
        return [r for r in rows if keep(r)]

    def _dedup(self, rows: list[dict]) -> list[dict]:
        seen_url: set[str] = set()
        seen_hash: list[int] = []
        out: list[dict] = []
        for row in rows:
            url = row.get("canonical_url") or row.get("url") or row.get("doc_id", "")
            if url in seen_url:
                continue
            signature = simhash(f"{row.get('title','')} {row.get('snippet','')}")
            if any(hamming(signature, h) <= 3 for h in seen_hash):
                continue
            seen_url.add(url)
            seen_hash.append(signature)
            out.append(row)
        return out

    def _rerank(self, rows: list[dict], filters: dict, query: str = "") -> list[dict]:
        weights = defaultdict(lambda: 1.0)
        try:
            with __import__("contextlib").closing(self.store._connect()) as db:
                for r in db.execute("SELECT source_id,trust_weight FROM sources"):
                    weights[r[0]] = float(r[1])
        except Exception:
            pass
        for row in rows:
            authority = weights.get(row.get("source_id") or "", 1.0)
            recency = 0.0
            fetched = str(row.get("fetched_at") or "")
            if fetched:
                recency = min(1.0, len(fetched) / 40.0)  # 有时间戳的轻微加分
            coverage = self._term_coverage(query, row)
            row["term_coverage"] = coverage
            # 整短语命中：区分「中标公告」与「招标公告」这类共享 2-gram 但语义不同的查询
            phrase = self._phrase_hit(query, row)
            row["phrase_hit"] = phrase
            # 有 RRF 分数时以融合分为主（多引擎共识），否则用单引擎归一化分
            base = float(row.get("rrf_score") or row.get("rank_normalized") or 0.0)
            row["final_score"] = round(
                0.36 * base
                + 0.22 * coverage
                + 0.22 * phrase
                + 0.10 * min(1.0, authority)
                + 0.10 * recency,
                4,
            )
        return sorted(rows, key=lambda r: r["final_score"], reverse=True)

    @staticmethod
    def _phrase_hit(query: str, row: dict) -> float:
        """整短语命中：标题命中 1.0，摘要命中 0.6，去尾缀核心词命中 0.4。"""
        text = query.strip()
        if not text:
            return 0.0
        title = row.get("title") or ""
        snippet = row.get("snippet") or ""
        if text in title:
            return 1.0
        if text in snippet:
            return 0.6
        core = QueryCoordinator._strip_generic_suffix(text)
        if core and (core in title):
            return 0.4
        if core and (core in snippet):
            return 0.2
        return 0.0

    @staticmethod
    def _strip_generic_suffix(query: str) -> str:
        """去掉「公告/项目/结果」等泛化尾缀，取核心词做补充召回。"""
        text = query.strip()
        for suffix in ("公告", "结果公告", "项目", "通知", "公示"):
            if text.endswith(suffix) and len(text) - len(suffix) >= 2:
                return text[: -len(suffix)].strip()
        return ""

    @staticmethod
    def _term_coverage(query: str, row: dict) -> float:
        text = query.strip()
        if not text:
            return 0.0
        compact = "".join(text.split())
        grams = [compact[i:i + 2] for i in range(max(1, len(compact) - 1))]
        grams = [g for g in dict.fromkeys(grams) if len(g) == 2] or [compact]
        haystack = f"{row.get('title') or ''} {row.get('snippet') or ''}"
        hit = sum(1 for g in grams if g in haystack)
        return round(hit / len(grams), 4)

    def _attach_facts(self, rows: list[dict], filters: dict) -> None:
        status_filter = filters.get("verification_status")
        with __import__("contextlib").closing(self.store._connect()) as db:
            for row in rows:
                dv = row.get("document_version_id")
                if not dv:
                    row["facts"] = []
                    continue
                clause = " AND fv.verification_status=?" if status_filter else ""
                params: list = [dv] + ([status_filter] if status_filter else [])
                row["facts"] = [dict(r) for r in db.execute(
                    """SELECT f.predicate, fv.normalized_value, fv.verification_status,
                              fv.fact_version_id, e.primary_name AS subject
                       FROM fact_evidences fe
                       JOIN fact_versions fv ON fv.fact_version_id=fe.fact_version_id
                       JOIN facts f ON f.fact_id=fv.fact_id
                       JOIN entities e ON e.entity_id=f.subject_id
                       WHERE fe.document_version_id=?""" + clause,
                    params,
                ).fetchall()]

    # ---------- 答案 ----------
    def render_answer(self, query: str, rows: list[dict]) -> str:
        if not rows:
            return f"查询「{query}」没有命中已索引文档。"
        lines = [f"查询：{query}", ""]
        used = 0
        for i, row in enumerate(rows[:8], 1):
            title = (row.get("title") or "").strip() or "(无标题)"
            url = row.get("canonical_url") or row.get("url") or ""
            citation = f"[{i}]" if url else "[无来源]"
            lines.append(f"{citation} {title}")
            if url:
                lines.append(f"    {url}")
            facts = row.get("facts") or []
            for fact in facts[:3]:
                status = fact.get("verification_status", "unverified")
                suffix = "" if status == "verified" else f"（{status}）"
                lines.append(f"    · {fact.get('predicate')}={fact.get('normalized_value')}{suffix}")
            used += 1
        lines.append("")
        lines.append(f"共 {used} 条引用结果；答案陈述均绑定上述 URL 与文档版本。")
        return "\n".join(lines)

    @staticmethod
    def _validate_citations(rows: list[dict]) -> bool:
        """引用完整性：每条结果的 URL 与 document_version_id 必须存在。"""
        for row in rows:
            if not (row.get("canonical_url") or row.get("url")):
                return False
            if not row.get("document_version_id"):
                return False
        return True

    def log(self, query: str, result: dict, latency_ms: int) -> None:
        self.store.log_query(query, result["routed_domains"],
                             [r.get("doc_id", "") for r in result["results"]], latency_ms)
