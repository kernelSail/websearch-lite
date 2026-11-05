"""P1 索引管理：从 SQLite 重建 Tantivy、写回 index_tasks 状态、对照评测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from websearch_lite.paths import find_project_root

ROOT = find_project_root()
from websearch_lite.app.crawl import load_config, load_domains, make_store, register_all
from websearch_lite.eval.p1_compare import compare
from websearch_lite.indexing import build_search_port
from websearch_lite.indexing.tantivy_port import TantivySearchPort


def build_tantivy(config: dict, store) -> TantivySearchPort:
    port = TantivySearchPort(config.get("tantivy_root", str(ROOT / "domains_index")))
    docs = store.all_index_documents()
    port.rebuild(docs)
    return port


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="p1-index")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rebuild", help="从 SQLite 全量重建 Tantivy 索引")
    sub.add_parser("compare", help="FTS5 vs Tantivy 固定查询集对照")
    sub.add_parser("stats", help="Tantivy 索引统计")
    args = parser.parse_args(argv)

    config = load_config()
    store = make_store(config)
    domains = load_domains()
    register_all(store, domains)

    if args.command == "rebuild":
        port = build_tantivy(config, store)
        print(json.dumps({"engine": "tantivy", "rebuilt": port.stats()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare":
        fts = build_search_port({**config, "search_engine": "fts5"}, store)
        tantivy = build_tantivy(config, store)
        print(json.dumps(compare({"fts5": fts, "tantivy": tantivy}), ensure_ascii=False, indent=2))
        return 0
    if args.command == "stats":
        port = TantivySearchPort(config.get("tantivy_root", str(ROOT / "domains_index")))
        print(json.dumps(port.stats(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
