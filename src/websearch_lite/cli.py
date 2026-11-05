"""P0 CLI."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from websearch_lite.paths import find_project_root
ROOT = find_project_root()

from websearch_lite.app.crawl import crawl, load_config, load_domains, make_store, probe, register_all
from websearch_lite.eval.p0_eval import run_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="websearch-lite", description="WebSearch Lite P0")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="robots + 站点可达性探测（P0 前置）")
    p_crawl = sub.add_parser("crawl", help="执行一次定向采集")
    p_crawl.add_argument("--domain", help="只跑指定域")
    p_crawl.add_argument("--max-pages", type=int)
    p_search = sub.add_parser("search", help="检索本地索引")
    p_search.add_argument("query")
    p_search.add_argument("--domain")
    p_search.add_argument("--limit", type=int, default=20)
    sub.add_parser("stats", help="库统计")
    sub.add_parser("health", help="来源健康")
    sub.add_parser("consistency", help="SQLite/索引一致性")
    sub.add_parser("eval", help="跑 P0 固定查询集评测")

    args = parser.parse_args(argv)
    config = load_config()
    domains = load_domains()
    if getattr(args, "domain", None):
        domains = {k: v for k, v in domains.items() if k == args.domain}
    store = make_store(config)
    register_all(store, domains)

    if args.command == "probe":
        rows = probe(config, domains)
        for row in rows:
            print(f"[{row['verdict']}] {row['domain_id']:22s} robots={row['robots_reason']:24s} http={row['http_status']}")
        return 0 if all(r["verdict"] == "PASS" for r in rows) else 1

    if args.command == "crawl":
        result = crawl(config, domains, store, max_pages=args.max_pages)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "search":
        started = time.perf_counter()
        rows = store.search(args.query, domain_id=args.domain, limit=args.limit)
        latency = int((time.perf_counter() - started) * 1000)
        store.log_query(args.query, list(domains), [r["doc_id"] for r in rows], latency)
        for i, row in enumerate(rows, 1):
            print(f"[{i}] {row['title'][:70]}\n    {row['canonical_url']}\n    ({row['domain_id']}, {row['fetched_at']})")
        print(f"\n{len(rows)} 条结果，{latency} ms")
        return 0

    if args.command == "stats":
        print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "health":
        for row in store.source_health():
            print(json.dumps(row, ensure_ascii=False))
        return 0

    if args.command == "consistency":
        print(json.dumps(store.consistency(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval":
        print(json.dumps(run_eval(store), ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())