"""P0 编排：probe / crawl / search / stats / health / consistency / eval。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common import canonicalize_url, now_iso
from ..crawler.adapters import build_adapter
from ..crawler.fetcher import Fetcher
from ..paths import find_project_root
from ..pipeline.runs import finish_run, start_run
from ..storage.sqlite_store import Store

ROOT = find_project_root()


def _meta_key(url: str) -> str:
    """URL 元数据匹配键：忽略 scheme/大小写/末尾斜杠差异。"""
    text = str(url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.rstrip("/")


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_domains() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted((ROOT / "domains").glob("*/domain.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        config["_path"] = str(path)
        out[config["id"]] = config
    return out


def make_store(config: dict) -> Store:
    return Store(config["database"], ROOT / "migrations")


def register_all(store: Store, domains: dict[str, dict]) -> None:
    for config in domains.values():
        store.register_domain(config, config["_path"])


def probe(config: dict, domains: dict[str, dict]) -> list[dict]:
    """P0 第一前置任务：robots + 站点可达性，FAIL 即剔除。"""
    fetcher = Fetcher(config)
    results = []
    for domain_id, cfg in domains.items():
        src = cfg["source"]
        base = src["base_url"]
        allowed, reason = fetcher.robots(base, cfg.get("robots_respect", True))
        reachable = False
        status = None
        if allowed:
            result = fetcher.fetch(base, rps=cfg.get("rate_limit_rps", 1.0), respect_robots=False, base_url=base)
            reachable = result.error is None and result.status_code == 200
            status = result.status_code
        results.append({
            "domain_id": domain_id, "source_id": src["id"], "base_url": base,
            "robots_allowed": allowed, "robots_reason": reason,
            "reachable": reachable, "http_status": status,
            "verdict": "PASS" if (allowed and reachable) else "FAIL",
        })
    return results


def crawl(config: dict, domains: dict[str, dict], store: Store, *, max_pages: int | None = None,
          due_only: bool = True) -> dict:
    """定向采集。due_only=True 时只取 next_run_at 已到期的任务（P5 增量语义）。"""
    run_id = start_run(store, config)
    fetcher = Fetcher(config)
    limit = max_pages or int(config["p0"]["max_pages_per_source"])
    summary: dict[str, Any] = {"run_id": run_id, "domains": {}}
    from .scheduler import Scheduler
    scheduler = Scheduler(store, config)

    for domain_id, cfg in domains.items():
        src = cfg["source"]
        source_id = src["id"]
        adapter = build_adapter(cfg.get("adapter", "generic"))
        selectors = [s.strip() for s in cfg.get("content_selector", "").split(",") if s.strip()]
        discovery = cfg.get("discovery", {})

        # 1) 发现 URL：站点适配器可提供 API 发现路径（巨潮 SPA 列表页无有效链接）
        discovered = 0
        api_items: dict[str, dict] = {}
        if hasattr(adapter, "discover_api"):
            for item in adapter.discover_api(limit * 2):
                # 按规范化 key 存元数据：API 返回 .pdf、站点链接可能 .PDF，大小写不一致
                api_items[_meta_key(item["url"])] = item
                if store.enqueue_url(source_id, item["url"], canonicalize_url(item["url"])):
                    discovered += 1
        for seed in discovery.get("seed_urls", []):
            seed_result = fetcher.fetch(seed, rps=cfg.get("rate_limit_rps", 1.0),
                                       respect_robots=cfg.get("robots_respect", True), base_url=src["base_url"])
            if seed_result.error or not seed_result.body:
                continue
            html = seed_result.body.decode("utf-8", errors="replace")
            for url in adapter.discover_urls(html, seed, limit * 2):
                if store.enqueue_url(source_id, url, canonicalize_url(url)):
                    discovered += 1

        # 2) 逐页采集：开启增量时只认领已到期任务，未到期保持 pending
        if due_only:
            due_ids = [t["crawl_task_id"] for t in scheduler.due_tasks(domain_id)]
            tasks = store.claim_crawl_tasks(source_id, due_ids, limit)
        else:
            tasks = store.next_crawl_tasks(source_id, limit)
        counters = {"discovered": discovered, "fetched": 0, "ingested": 0,
                    "reused": 0, "failed": 0, "skipped_304": 0,
                    "deferred": max(0, len(due_ids) - len(tasks)) if due_only else 0}
        temp_root = Path(config["temp_root"]) / run_id
        temp_root.mkdir(parents=True, exist_ok=True)

        for task in tasks:
            url = task["url"]
            result = fetcher.fetch(url, etag=task["etag"], last_modified=task["last_modified"],
                                   rps=cfg.get("rate_limit_rps", 1.0),
                                   respect_robots=cfg.get("robots_respect", True), base_url=src["base_url"])
            if result.error_code == "ROBOTS_DISALLOWED":
                store.finish_crawl(task["crawl_task_id"], "skipped", error=result.error)
                store.update_source_health(source_id, False, result.error)
                counters["failed"] += 1
                continue
            if result.from_cache:
                store.finish_crawl(task["crawl_task_id"], "succeeded", http_status=304,
                                   etag=task["etag"], last_modified=task["last_modified"])
                counters["skipped_304"] += 1
                continue
            if result.error or not result.body:
                store.finish_crawl(task["crawl_task_id"], "failed", http_status=result.status_code,
                                   error=result.error)
                store.update_source_health(source_id, False, result.error)
                counters["failed"] += 1
                continue

            # 短期正文缓存：抽取前写入 temp，入库后即删
            api_meta = api_items.get(_meta_key(url))
            is_pdf_binary = result.body[:5] == b"%PDF-"
            if is_pdf_binary and not api_meta:
                # PDF 二进制且无 API 元数据（典型：上一轮发现、本轮未在 API 结果里的老任务）
                # 绝不把 PDF 字节当正文入库，明确标记为不可处理
                store.finish_crawl(task["crawl_task_id"], "succeeded", http_status=result.status_code,
                                   etag=result.headers.get("etag"),
                                   last_modified=result.headers.get("last-modified"),
                                   error="PDF_WITHOUT_METADATA")
                counters["skipped_pdf"] = counters.get("skipped_pdf", 0) + 1
                continue
            if api_meta and api_meta.get("pdf"):
                # PDF 公告不下载二进制（P0 只存索引与元数据）；从 API 元数据构造可检索文本
                raw = ""
                text = "\n".join(filter(None, [
                    api_meta["title"], f"证券代码：{api_meta.get('sec_code', '')}",
                    f"证券简称：{api_meta.get('sec_name', '')}",
                    f"公告日期：{api_meta.get('published_at', '')}",
                ]))
                title = api_meta["title"]
                metadata = {"title": title, "published_at": None, "url": url,
                            "doc_type": "announcement", "source": "cninfo-api"}
                content = {"title": title, "text": text, "extraction_status": "partial"}
                doc_type = "announcement"
            else:
                raw = result.body.decode("utf-8", errors="replace")
            cache_file = temp_root / (task["crawl_task_id"] + ".html")
            if config["p0"].get("allow_short_term_text_cache", True) and raw:
                cache_file.write_text(raw, encoding="utf-8")
            try:
                if not (api_meta and api_meta.get("pdf")):
                    content = adapter.extract_content(raw, url, selectors)
                    metadata = adapter.extract_metadata(raw, url)
                    doc_type = adapter.classify_document_type(metadata, content["text"])
                    title = content["title"] or metadata.get("title", "")
                    text = content["text"]
                if not text:
                    store.finish_crawl(task["crawl_task_id"], "failed", error="EXTRACTION_FAILED")
                    store.update_source_health(source_id, False, "EXTRACTION_FAILED")
                    counters["failed"] += 1
                    continue
                ingested = store.ingest(
                    domain_id=domain_id, source_id=source_id, url=url,
                    canonical_url=task["canonical_url"], title=title,
                    text=text, published_at=metadata.get("published_at"), fetched_at=result.fetched_at,
                    http_status=result.status_code, etag=result.headers.get("etag"),
                    last_modified=result.headers.get("last-modified"),
                    extraction_status=content["extraction_status"], metadata=metadata,
                    doc_type=doc_type, run_id=run_id,
                    snippet_limit=int(config["p0"]["max_snippet_chars"]),
                    evidence_limit=int(config["p0"]["max_evidence_chars"]),
                )
                counters["fetched"] += 1
                if ingested["new_version"]:
                    counters["ingested"] += 1
                    # P2：结构化抽取（仅新版本，避免重复生成事实）
                    if config.get("p2", {}).get("extract_on_ingest", True):
                        try:
                            from ..facts.extractor import FactExtractor
                            extractor = FactExtractor(store, domain_id, config=config)
                            extract_meta = dict(metadata or {})
                            extract_meta["source_id"] = source_id
                            if api_meta:
                                extract_meta.update({k: api_meta[k] for k in
                                                     ("sec_code", "sec_name", "published_at") if api_meta.get(k)})
                            extracted = extractor.extract_document(
                                document_version_id=ingested["document_version_id"],
                                text=text, metadata=extract_meta, run_id=run_id,
                            )
                            counters["facts_created"] = counters.get("facts_created", 0) + extracted["created"]
                        except Exception as error:
                            counters["extract_failed"] = counters.get("extract_failed", 0) + 1
                            store.finish_crawl(task["crawl_task_id"], "succeeded",
                                               http_status=result.status_code,
                                               etag=result.headers.get("etag"),
                                               last_modified=result.headers.get("last-modified"),
                                               error=f"P2_EXTRACT_FAILED:{error}")
                else:
                    counters["reused"] += 1
                store.finish_crawl(task["crawl_task_id"], "succeeded", http_status=result.status_code,
                                   etag=result.headers.get("etag"),
                                   last_modified=result.headers.get("last-modified"))
                store.update_source_health(source_id, True)
            finally:
                if cache_file.exists():
                    cache_file.unlink()
        # 清理本次 run 的临时目录
        try:
            temp_root.rmdir()
        except OSError:
            pass
        summary["domains"][domain_id] = counters

    finish_run(store, run_id)
    return summary
