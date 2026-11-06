"""Tantivy 检索投影（P1）。索引可从 SQLite 重建，不作为事实副本。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tantivy

from .tokenizer import query_tokens, tokenize  # noqa: F401  （统一分词入口）


class TantivySearchPort:
    name = "tantivy"

    def __init__(self, index_root: str | Path) -> None:
        self.root = Path(index_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.domains: dict[str, dict[str, Any]] = {}
        self._load_existing()

    def _schema(self):
        builder = tantivy.SchemaBuilder()
        # 分词字段（仅用于检索，不存储）：写入的是 jieba 预分词后的空格串
        builder.add_text_field("title", stored=False, tokenizer_name="default")
        builder.add_text_field("snippet", stored=False, tokenizer_name="default")
        builder.add_text_field("entities", stored=False, tokenizer_name="default")
        # 原文存储字段（仅用于回显，不分词）：避免把分词结果当标题展示给用户
        builder.add_text_field("title_text", stored=True, tokenizer_name="raw")
        builder.add_text_field("snippet_text", stored=True, tokenizer_name="raw")
        builder.add_text_field("url", stored=True, tokenizer_name="raw")
        builder.add_text_field("canonical_url", stored=True, tokenizer_name="raw")
        builder.add_text_field("domain_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("source_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("document_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("document_version_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("published_at", stored=True, tokenizer_name="raw")
        builder.add_text_field("fetched_at", stored=True, tokenizer_name="raw")
        return builder.build()

    def _domain_index(self, domain_id: str) -> dict[str, Any]:
        if domain_id in self.domains:
            return self.domains[domain_id]
        path = self.root / domain_id
        path.mkdir(parents=True, exist_ok=True)
        schema = self._schema()
        index = tantivy.Index(schema, path=str(path))
        self.domains[domain_id] = {"index": index, "path": path, "writer": None}
        return self.domains[domain_id]

    def _load_existing(self) -> None:
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                index = tantivy.Index.open(str(path))
                self.domains[path.name] = {"index": index, "path": path, "writer": None}
            except Exception:
                continue

    def _writer(self, domain_id: str):
        entry = self._domain_index(domain_id)
        if entry["writer"] is None:
            entry["writer"] = entry["index"].writer()
        return entry["writer"]

    def _commit(self, domain_id: str) -> None:
        entry = self.domains.get(domain_id)
        if entry and entry["writer"] is not None:
            entry["writer"].commit()
            entry["index"].reload()
            entry["writer"] = None

    def _document(self, doc: dict) -> tantivy.Document:
        title = doc.get("title") or ""
        snippet = doc.get("snippet") or ""
        return tantivy.Document(
            doc_id=doc["doc_id"],
            document_id=doc.get("document_id", doc["doc_id"]),
            title=tokenize(title),
            snippet=tokenize(snippet),
            entities=tokenize(doc.get("entities") or ""),
            title_text=title,
            snippet_text=snippet,
            url=doc.get("url") or "",
            canonical_url=doc.get("canonical_url") or "",
            domain_id=doc.get("domain_id") or "",
            source_id=doc.get("source_id") or "",
            document_version_id=doc.get("document_version_id") or "",
            published_at=doc.get("published_at") or "",
            fetched_at=doc.get("fetched_at") or "",
        )

    def upsert(self, doc_id: str, document: dict) -> None:
        domain_id = document.get("domain_id") or "default"
        entry = self._domain_index(domain_id)
        writer = self._writer(domain_id)
        writer.delete_documents("doc_id", doc_id)
        writer.add_document(self._document({**document, "doc_id": doc_id}))
        self._commit(domain_id)

    def delete(self, doc_id: str, domain_id: str | None = None) -> None:
        targets = [domain_id] if domain_id else list(self.domains) or [p.name for p in self.root.iterdir() if p.is_dir()]
        for did in targets:
            try:
                writer = self._writer(did)
                writer.delete_documents("doc_id", doc_id)
                self._commit(did)
            except Exception:
                continue

    def search(self, query: str, *, filters: dict | None = None, limit: int = 20) -> list[dict]:
        filters = filters or {}
        domain_ids = [filters["domain_id"]] if filters.get("domain_id") else list(self.domains)
        tokens = query_tokens(query)
        if not tokens:
            return []  # 全部是停用词/标点：没有可检索内容，返回空而不是匹配所有文档
        # AND 优先保证精确（「中标公告」要求同时含 中标+公告），召回不足时退化为 OR。
        # OR 仅在有效 token >= 2 时启用；单个 token 走 OR 等价于全表扫描噪声。
        strategies = [" AND ".join(tokens)]
        if len(tokens) >= 2:
            strategies.append(" OR ".join(tokens))
        hits: list[dict] = []
        for domain_id in domain_ids:
            entry = self._domain_index(domain_id)
            try:
                entry["index"].reload()
                searcher = entry["index"].searcher()
            except Exception:
                continue
            for query_text in strategies:
                try:
                    parsed = entry["index"].parse_query(query_text, ["title", "snippet", "entities"])
                    found = searcher.search(parsed, limit=limit).hits
                except Exception:
                    found = []
                if not found:
                    continue
                seen_ids = {h.get("doc_id") for h in hits}
                for score, address in found:
                    doc = searcher.doc(address)
                    raw = doc.to_dict() if hasattr(doc, "to_dict") else dict(doc)
                    item = {key: (value[0] if isinstance(value, list) and value else value)
                            for key, value in raw.items()}
                    if item.get("doc_id") in seen_ids:
                        continue
                    # 回显用原文，检索用分词字段
                    item["title"] = item.pop("title_text", "") or item.get("title", "")
                    item["snippet"] = item.pop("snippet_text", "") or item.get("snippet", "")
                    item["score"] = float(score)
                    item["domain_id"] = domain_id
                    hits.append(item)
                # AND 已凑够本域所需条数才停止；不足时继续用 OR 补召回
                if len([h for h in hits if h.get("domain_id") == domain_id]) >= limit:
                    break
        # 域内归一化 rank，避免直接比较不同域的原始 BM25 分（V1.1 §12.3）
        by_domain: dict[str, list[dict]] = {}
        for item in hits:
            by_domain.setdefault(item["domain_id"], []).append(item)
        merged: list[dict] = []
        for items in by_domain.values():
            items.sort(key=lambda x: x["score"], reverse=True)
            total = len(items) or 1
            for rank, item in enumerate(items):
                item["rank_normalized"] = round(1.0 - rank / total, 4)
                item["raw_score"] = item["score"]
                merged.append(item)
        merged.sort(key=lambda x: x["rank_normalized"], reverse=True)
        return merged[:limit]

    def stats(self) -> dict:
        return {
            "engine": self.name,
            "domains": {did: entry["index"].searcher().num_docs for did, entry in self.domains.items()},
            "total": sum(entry["index"].searcher().num_docs for entry in self.domains.values()),
        }

    def rebuild(self, documents: list[dict]) -> None:
        """从 SQLite 的 documents_index 全量重建（V1.1 §11.4）。"""
        import shutil
        # 先释放当前进程持有的 writer / index，再删除目录（Windows 文件锁）
        for entry in self.domains.values():
            entry["writer"] = None
        self.domains.clear()
        for path in list(self.root.iterdir()):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        # 目录被删后重新创建，避免后续 Index 写入失败
        self.root.mkdir(parents=True, exist_ok=True)
        pending: dict[str, list[dict]] = {}
        for doc in documents:
            doc = dict(doc)
            doc.setdefault("doc_id", doc.get("document_id", "unknown"))
            pending.setdefault(doc.get("domain_id") or "default", []).append(doc)
        # 按域批量写入：每个域一个 writer，最后统一 commit
        for domain_id, docs in pending.items():
            entry = self._domain_index(domain_id)
            writer = entry["index"].writer()
            for doc in docs:
                writer.add_document(self._document(doc))
            writer.commit()
            entry["index"].reload()
        self.domains.clear()
        self._load_existing()
