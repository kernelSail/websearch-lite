"""Verifier：事实验证、冲突快照、权威裁决、复核队列（V1.1 §8）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..common import dumps, loads, now_iso, short_id
from .source_graph import build_source_graph
from .state import assert_transition, build_components, decide_status, decision_reason


class Verifier:
    def __init__(self, store, config: dict | None = None) -> None:
        self.store = store
        self.config = config or {}
        self.stale_days = int(self.config.get("verification", {}).get("stale_days", 180))
        self.graph = build_source_graph(store)
        self.graph.detect_reposts()
        self.graph.to_db(store, run_id=None)

    # ---------- 单个事实版本 ----------
    def verify(self, fact_version_id: str) -> dict:
        with __import__("contextlib").closing(self.store._connect()) as db:
            fv = db.execute("SELECT * FROM fact_versions WHERE fact_version_id=?", (fact_version_id,)).fetchone()
            if not fv:
                return {"found": False, "fact_version_id": fact_version_id}
            fact = db.execute("SELECT * FROM facts WHERE fact_id=?", (fv["fact_id"],)).fetchone()
            evidences = [dict(r) for r in db.execute(
                """SELECT e.*, s.role, s.authority_scope_json, s.trust_weight
                   FROM fact_evidences e JOIN sources s ON s.source_id=e.source_id
                   WHERE e.fact_version_id=?""", (fact_version_id,)
            ).fetchall()]

            doc_ids = [e["document_version_id"] for e in evidences]
            independent_count, clusters = self.graph.independent_clusters(doc_ids)

            roles = [e["role"] for e in evidences]
            authority_level = "authoritative" if "authoritative" in roles else (
                "corroborating" if "corroborating" in roles else "reference")

            # 同一 fact 的其它版本值是否冲突
            others = [dict(r) for r in db.execute(
                "SELECT fact_version_id,normalized_value,verification_status FROM fact_versions WHERE fact_id=? AND fact_version_id!=?",
                (fact["fact_id"], fact_version_id),
            ).fetchall()]
            conflicting_values = [o for o in others if o["normalized_value"] != fv["normalized_value"]
                                  and o["verification_status"] != "rejected"]
            consistency = "conflicting" if conflicting_values else "consistent"

            freshness = self._freshness(fv, evidences)
            extraction_quality = "passed" if evidences and all(e["quoted_text"] for e in evidences) else "failed"
            components = build_components(
                independent_source_count=independent_count,
                authority_level=authority_level,
                evidence_consistency=consistency,
                freshness=freshness,
                extraction_quality=extraction_quality,
            )
            target = decide_status(components)
            current = fv["verification_status"]
            assert_transition(current, target)
            reason = decision_reason(components, target)

            now = now_iso()
            db.execute(
                """UPDATE fact_versions SET verification_status=?, verification_summary=?,
                     verified_at=? WHERE fact_version_id=?""",
                (target, reason, now, fact_version_id),
            )

            # 冲突快照：不静默覆盖，保留被比较版本
            if consistency == "conflicting":
                snapshot = {
                    "fact_id": fact["fact_id"],
                    "current": {"fact_version_id": fact_version_id, "value": fv["normalized_value"]},
                    "competing": [{"fact_version_id": o["fact_version_id"], "value": o["normalized_value"]}
                                  for o in conflicting_values],
                    "components": components,
                    "decided_at": now,
                }
                cid = short_id("conf", fact["fact_id"], fact_version_id)
                db.execute(
                    """INSERT OR IGNORE INTO fact_conflicts
                       (conflict_id,fact_id,status,conflict_snapshot_json,winner_fact_version_id,
                        decision_reason,decided_by,decided_at,created_at,updated_at)
                       VALUES (?,?,'open',?,?,?,?,?,?,?)""",
                    (cid, fact["fact_id"], dumps(snapshot), None,
                     "auto: conflicting versions retained, no silent override", "verifier-v1", now, now, now),
                )
                self._enqueue_review(db, "fact_verification", "fact_version", fact_version_id,
                                     "conflicting values require human review", snapshot)

            # 抽取质量失败 / 状态异常 → 复核
            if extraction_quality != "passed" or target == "rejected":
                self._enqueue_review(db, "fact_verification", "fact_version", fact_version_id,
                                     f"status={target}, extraction={extraction_quality}", components)

            db.commit()
            return {
                "found": True, "fact_version_id": fact_version_id,
                "from": current, "to": target, "components": components,
                "reason": reason, "conflict": consistency == "conflicting",
            }

    def _freshness(self, fv, evidences: list[dict]) -> str:
        candidates = [fv["occurred_at"], fv["published_at"], fv["created_at"]]
        for e in evidences:
            candidates.append(e.get("created_at"))
        timestamps = []
        for value in candidates:
            if not value:
                continue
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                timestamps.append(dt)
            except (ValueError, TypeError):
                continue
        if not timestamps:
            return "unknown"
        days = (datetime.now(timezone.utc) - max(timestamps)).days
        return "expired" if days > self.stale_days else "current"

    @staticmethod
    def _enqueue_review(db, task_type: str, target_type: str, target_id: str,
                        reason: str, payload: dict) -> None:
        now = now_iso()
        db.execute(
            """INSERT OR IGNORE INTO review_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (short_id("rev", task_type, target_id), task_type, target_type, target_id,
             "pending", 1, reason, dumps(payload), None, now, now, None),
        )

    # ---------- 批量 ----------
    def verify_all(self, *, domain_id: str | None = None) -> dict:
        with __import__("contextlib").closing(self.store._connect()) as db:
            clause = " WHERE f.domain_id=?" if domain_id else ""
            params = [domain_id] if domain_id else []
            ids = [r[0] for r in db.execute(
                "SELECT fv.fact_version_id FROM fact_versions fv JOIN facts f ON f.fact_id=fv.fact_id" + clause,
                params,
            ).fetchall()]
        results = {"total": len(ids), "verified": 0, "single-source": 0,
                   "conflicting": 0, "stale": 0, "rejected": 0, "errors": []}
        for fid in ids:
            try:
                out = self.verify(fid)
                if out.get("to"):
                    results[out["to"]] = results.get(out["to"], 0) + 1
            except Exception as error:
                results["errors"].append({"fact_version_id": fid, "error": str(error)})
        return results

    # ---------- 权威裁决 ----------
    def resolve_conflict(self, conflict_id: str, winner_fact_version_id: str,
                         *, decided_by: str = "human", reason: str = "") -> dict:
        with __import__("contextlib").closing(self.store._connect()) as db:
            conf = db.execute("SELECT * FROM fact_conflicts WHERE conflict_id=?", (conflict_id,)).fetchone()
            if not conf:
                return {"found": False, "conflict_id": conflict_id}
            if conf["status"] != "open":
                return {"found": True, "already": conf["status"]}
            now = now_iso()
            db.execute(
                """UPDATE fact_conflicts SET status='resolved', winner_fact_version_id=?,
                     decision_reason=?, decided_by=?, decided_at=?, updated_at=? WHERE conflict_id=?""",
                (winner_fact_version_id, reason or "human adjudication", decided_by, now, now, conflict_id),
            )
            # 胜出版本迁移到 verified（写快照已满足 conflicting→verified 条件）
            db.execute(
                "UPDATE fact_versions SET verification_status='verified', verification_summary=?, verified_at=? WHERE fact_version_id=?",
                (f"resolved by {decided_by}: {reason}", now, winner_fact_version_id),
            )
            db.execute(
                "UPDATE review_tasks SET status='resolved', resolved_at=? WHERE target_type='fact_version' AND target_id=? AND status='pending'",
                (now, winner_fact_version_id),
            )
            db.commit()
            return {"found": True, "conflict_id": conflict_id, "winner": winner_fact_version_id,
                    "status": "resolved"}
