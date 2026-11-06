"""事实抽取：封闭 Schema 规则匹配 → 候选表 → 校验 → 事实/版本/证据落库。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..common import dumps, now_iso, sha256_text, short_id
from ..paths import find_project_root
from .entity_resolve import EntityResolver
from .normalize import find_span, normalize_value

ROOT = find_project_root()


def load_schema(domain_id: str) -> dict:
    path = ROOT / "domains" / domain_id / "schema"
    for candidate in sorted(path.glob("*.json")):
        return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no schema for {domain_id}")


class RuleClassifier:
    """封闭 Schema 的确定性抽取器（P2 基线，模型可替换）。"""

    def __init__(self, schema: dict) -> None:
        self.schema = schema

    def classify(self, text: str, *, metadata: dict | None = None) -> dict:
        metadata = metadata or {}
        fields: dict[str, dict] = {}
        for spec in self.schema.get("facts", []):
            predicate = spec["predicate"]
            raw = None
            for pattern in spec.get("patterns", []):
                match = re.search(pattern, text, re.I)
                if match:
                    raw = match.group(1) if match.lastindex else match.group(0)
                    break
            if raw is None:
                continue
            # 元数据只作为「文本未抽到」时的兜底，且必须与当前文本一致；
            # 不能让上一条文档的 metadata 覆盖当前文档的字段（否则产生伪证据）。
            if predicate in ("sec_code", "sec_name") and metadata.get(predicate) and raw is None:
                raw = metadata[predicate]
            normalized = normalize_value(spec.get("value_type", "text"), raw)
            char_start, char_end, quote = find_span(text, str(raw))
            fields[predicate] = {
                "raw": str(raw),
                "normalized": normalized["normalized"],
                "structured": normalized["structured"],
                "unit": normalized["unit"],
                "currency": normalized["currency"],
                "error": normalized["error"],
                "evidence": {"char_start": char_start, "char_end": char_end, "quoted_text": quote},
            }
        return {
            "schema_id": self.schema["schema_id"],
            "fields": fields,
            "entity_fields": {k: v["normalized"] for k, v in fields.items()},
        }


class FactExtractor:
    def __init__(self, store, domain_id: str, schema: dict | None = None) -> None:
        self.store = store
        self.domain_id = domain_id
        self.schema = schema or load_schema(domain_id)
        self.classifier = RuleClassifier(self.schema)
        self.resolver = EntityResolver(store, self.schema)

    def extract_document(self, *, document_version_id: str, text: str,
                         metadata: dict | None = None, run_id: str | None = None) -> dict:
        result = self.classifier.classify(text, metadata=metadata or {})
        fields = result["fields"]
        now = now_iso()
        with __import__("contextlib").closing(self.store._connect()) as probe_db:
            source_row = probe_db.execute(
                """SELECT d.source_id FROM documents d
                   JOIN document_versions dv ON dv.document_id=d.document_id
                   WHERE dv.document_version_id=?""", (document_version_id,)
            ).fetchone()
        effective_source_id = (metadata or {}).get("source_id") or (source_row[0] if source_row else None)
        resolution = self.resolver.resolve(domain_id=self.domain_id, fields=result["entity_fields"])
        entity_id = resolution["entity_id"]

        with __import__("contextlib").closing(self.store._connect()) as db:
            # 1) 原始候选先落表（评审补齐 ③）
            for predicate, field in fields.items():
                candidate_id = short_id("cand", document_version_id, predicate)
                db.execute(
                    """INSERT OR REPLACE INTO raw_fact_candidates
                       (candidate_id,document_version_id,run_id,raw_json,schema_version,
                        validation_status,reject_reason,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (candidate_id, document_version_id, run_id, dumps(field),
                     self.schema["schema_id"], "accepted" if not field["error"] else "rejected",
                     field["error"], now),
                )

            # 2) 通过校验的候选 → facts / fact_versions / fact_evidences
            created = 0
            for predicate, field in fields.items():
                if field["error"]:
                    continue
                subject_id = entity_id
                fact_id = short_id("fact", self.domain_id, subject_id, predicate)
                db.execute(
                    """INSERT OR IGNORE INTO facts(fact_id,domain_id,subject_id,predicate,
                         normalized_scope,created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                    (fact_id, self.domain_id, subject_id, predicate, "", now, now),
                )
                version_no = db.execute(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM fact_versions WHERE fact_id=?", (fact_id,)
                ).fetchone()[0]
                value_json = {"raw": field["raw"], "normalized": field["normalized"]}
                if field["structured"]:
                    value_json["structured"] = field["structured"]
                fv_id = short_id("fv", fact_id, field["normalized"])
                existing = db.execute(
                    "SELECT fact_version_id FROM fact_versions WHERE fact_id=? AND normalized_value=?",
                    (fact_id, field["normalized"]),
                ).fetchone()
                if existing:
                    continue  # 同值不重复建版本
                db.execute(
                    """INSERT INTO fact_versions
                       (fact_version_id,fact_id,version_no,value_json,normalized_value,unit,currency,
                        published_at,occurred_at,valid_from,valid_to,verification_status,
                        verification_summary,verified_at,extractor_model,schema_version,
                        confidence_raw,run_id,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,'unverified',?,?,?,?,?,?,?)""",
                    (fv_id, fact_id, version_no, dumps(value_json), field["normalized"],
                     field["unit"], field["currency"], (metadata or {}).get("published_at"),
                     (metadata or {}).get("occurred_at"), None, None,
                     None, None, "rule-classifier-v1", self.schema["schema_id"],
                     resolution["confidence"], run_id, now),
                )
                ev = field["evidence"]
                db.execute(
                    """INSERT INTO fact_evidences VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (short_id("ev", fv_id, document_version_id), fv_id, document_version_id,
                     effective_source_id, 0, ev["char_start"], ev["char_end"],
                     ev["quoted_text"], "supports", sha256_text(ev["quoted_text"]), now),
                )
                created += 1
            if resolution["needs_review"]:
                db.execute(
                    """INSERT OR IGNORE INTO review_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (short_id("rev", "extract", document_version_id), "entity_resolution", "document_version",
                     document_version_id, "pending", 1, resolution["reason"], "{}", None, now, now, None),
                )
            db.commit()
            return {"schema_id": self.schema["schema_id"], "candidates": len(fields),
                    "created": created, "entity_id": entity_id,
                    "confidence": resolution["confidence"], "needs_review": resolution["needs_review"]}
