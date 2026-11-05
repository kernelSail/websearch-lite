"""按 config 构建 SearchPort：P0 FTS5 / P1 Tantivy。"""
from __future__ import annotations

from pathlib import Path

from .fts5_port import Fts5SearchPort
from .port import SearchPort


def build_search_port(config: dict, store) -> SearchPort:
    engine = config.get("search_engine", "fts5")
    if engine == "tantivy":
        from .tantivy_port import TantivySearchPort
        root = Path(config.get("tantivy_root", "D:/study/deepseek-work/websearch-lite/domains_index"))
        return TantivySearchPort(root)
    return Fts5SearchPort(store)
