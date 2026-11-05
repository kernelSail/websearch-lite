"""处理运行与规则版本登记（评审补齐 ④）。"""
from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path

from ..common import now_iso, short_id


def start_run(store, config: dict, code_version: str = "p0.1") -> str:
    run_id = short_id("run", now_iso(), code_version)
    config_hash = hashlib.sha256(
        __import__("json").dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    with closing(store._connect()) as db:
        db.execute(
            """INSERT INTO processing_runs
               (run_id,started_at,git_sha,code_version,model_name,model_endpoint,prompt_version,
                rule_version,schema_version,config_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, now_iso(), None, code_version,
             config.get("classifier", {}).get("model"),
             config.get("classifier", {}).get("local_endpoint"),
             "none", "rule-v1", "multi", config_hash),
        )
        db.commit()
    return run_id


def finish_run(store, run_id: str) -> None:
    with closing(store._connect()) as db:
        db.execute("UPDATE processing_runs SET finished_at=? WHERE run_id=?", (now_iso(), run_id))
        db.commit()
