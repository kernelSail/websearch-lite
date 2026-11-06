"""常驻调度循环：按周期抓到期任务，并做恢复与一致性检查（P5 完善）。"""
from __future__ import annotations

import json
import sys
import time
import traceback

from ..app.crawl import crawl
from ..app.recovery import Recovery
from ..app.scheduler import Scheduler
from ..storage.consistency import check_consistency
from ..indexing import build_search_port


def run_once(config: dict, domains: dict, store, *, max_pages: int | None = None) -> dict:
    recovery = Recovery(store, config)
    recover_result = recovery.run()
    scheduler = Scheduler(store, config)
    due = scheduler.due_tasks()
    result: dict = {"due": len(due), "recovery": recover_result, "crawl": None, "consistency": None}
    if due:
        result["crawl"] = crawl(config, domains, store, max_pages=max_pages)
    port = build_search_port(config, store)
    result["consistency"] = check_consistency(store, port, config)
    return result


def run_daemon(config: dict, domains: dict, store, *, interval: int = 900,
               once: bool = False, max_pages: int | None = None) -> int:
    rounds = 0
    while True:
        rounds += 1
        started = time.time()
        try:
            result = run_once(config, domains, store, max_pages=max_pages)
        except KeyboardInterrupt:
            print("\nreceived interrupt, exiting", file=sys.stderr)
            return 130
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)
            result = {"error": "round_failed"}
        result["round"] = rounds
        result["elapsed_s"] = round(time.time() - started, 2)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if once:
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 130
