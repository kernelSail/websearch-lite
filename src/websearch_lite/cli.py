"""P0–P2 CLI。"""
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
from websearch_lite.eval.p2_eval import evaluate as evaluate_p2
from websearch_lite.eval.p3_eval import evaluate as evaluate_p3
from websearch_lite.eval.p4_eval import evaluate as evaluate_p4
from websearch_lite.facts.extractor import FactExtractor
from websearch_lite.pipeline.runs import finish_run, start_run
from websearch_lite.query.coordinator import QueryCoordinator
from websearch_lite.verification.verifier import Verifier


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
    p_extract = sub.add_parser("extract", help="P2：补跑结构化事实抽取")
    p_extract.add_argument("--domain")
    sub.add_parser("eval2", help="P2：字段级 P/R/F1 评测")
    p_facts = sub.add_parser("facts", help="查看已抽取的结构化事实")
    p_facts.add_argument("--domain")
    p_facts.add_argument("--limit", type=int, default=50)
    p_verify = sub.add_parser("verify", help="P3：批量事实验证")
    p_verify.add_argument("--domain")
    sub.add_parser("eval3", help="P3：验证规则层评测")
    p_conf = sub.add_parser("conflicts", help="P3：查看冲突快照")
    p_conf.add_argument("--resolve")
    p_conf.add_argument("--winner")
    p_conf.add_argument("--reason", default="")
    p_rev = sub.add_parser("review", help="P3：查看人工复核队列")
    p_rev.add_argument("--limit", type=int, default=50)
    p_ask = sub.add_parser("ask", help="P4：统一查询 + 带引用答案")
    p_ask.add_argument("query")
    p_ask.add_argument("--domain")
    p_ask.add_argument("--limit", type=int, default=10)
    p_ask.add_argument("--since")
    p_ask.add_argument("--until")
    p_ask.add_argument("--status", help="事实状态过滤：verified/single-source/conflicting/stale")
    sub.add_parser("eval4", help="P4：Recall@K / nDCG@K / 引用正确率评测")

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

    if args.command == "extract":
        run_id = start_run(store, config, code_version="p2.1")
        extractors = {d: FactExtractor(store, d) for d in domains}
        totals = {"versions": 0, "created": 0, "failed": 0}
        for row in store.all_document_versions():
            if args.domain and row["domain_id"] != args.domain:
                continue
            try:
                result = extractors[row["domain_id"]].extract_document(
                    document_version_id=row["document_version_id"],
                    text=row["snippet"] or "",
                    metadata={"source_id": row["source_id"], "published_at": row["published_at"]},
                    run_id=run_id,
                )
                totals["versions"] += 1
                totals["created"] += result["created"]
            except Exception as error:
                totals["failed"] += 1
                print(f"EXTRACT_FAILED {row['document_version_id']}: {error}", file=sys.stderr)
        finish_run(store, run_id)
        totals["run_id"] = run_id
        print(json.dumps(totals, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval2":
        print(json.dumps(evaluate_p2(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "facts":
        print(json.dumps(store.list_facts(domain_id=args.domain, limit=args.limit),
                         ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify":
        verifier = Verifier(store, config)
        print(json.dumps(verifier.verify_all(domain_id=args.domain), ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval3":
        print(json.dumps(evaluate_p3(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "conflicts":
        if args.resolve:
            if not args.winner:
                print("--winner required when --resolve is used", file=sys.stderr)
                return 1
            verifier = Verifier(store, config)
            print(json.dumps(verifier.resolve_conflict(args.resolve, args.winner, reason=args.reason),
                             ensure_ascii=False, indent=2))
        else:
            print(json.dumps(store.list_conflicts(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "review":
        print(json.dumps(store.list_reviews(limit=args.limit), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ask":
        coordinator = QueryCoordinator(store, config)
        filters: dict = {}
        if args.domain:
            filters["domain_id"] = args.domain
        if args.since:
            filters["since"] = args.since
        if args.until:
            filters["until"] = args.until
        if args.status:
            filters["verification_status"] = args.status
        started = time.perf_counter()
        result = coordinator.search(args.query, filters=filters, limit=args.limit)
        latency = int((time.perf_counter() - started) * 1000)
        coordinator.log(args.query, result, latency)
        if result["citations_valid"] is False:
            print("警告：引用完整性检查失败（存在缺 URL 或文档版本的结果）", file=sys.stderr)
        print(result["answer"])
        print(f"\n[routed={','.join(result['routed_domains'])} | {latency} ms]")
        return 0

    if args.command == "eval4":
        print(json.dumps(evaluate_p4(QueryCoordinator(store, config)), ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())