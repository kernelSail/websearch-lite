"""实体解析：稳定标识优先，无稳定标识不自动合并，低置信进复核队列。"""
from __future__ import annotations

from typing import Any

from ..common import now_iso, short_id
from .normalize import normalize_text


class EntityResolver:
    def __init__(self, store, schema: dict) -> None:
        self.store = store
        self.schema = schema
        self.config = schema.get("entity_resolution", {})

    def _stable_id(self, fields: dict[str, str]) -> str | None:
        for key in self.config.get("stable_id_fields", []):
            value = normalize_text(fields.get(key, ""))
            if value:
                return f"{key}:{value}"
        return None

    def _candidates(self, fields: dict[str, str]) -> list[str]:
        out = []
        for key in self.config.get("candidate_fields", []):
            value = normalize_text(fields.get(key, ""))
            if value and value not in out:
                out.append(value)
        return out

    def resolve(self, *, domain_id: str, fields: dict[str, str]) -> dict:
        """返回 {entity_id, confidence, needs_review, reason, aliases}。"""
        stable = self._stable_id(fields)
        candidates = self._candidates(fields)
        now = now_iso()

        with __import__("contextlib").closing(self.store._connect()) as db:
            if stable:
                # 稳定标识存在：按 uscc/稳定键查找或新建
                row = db.execute(
                    "SELECT * FROM entities WHERE domain_id=? AND (uscc=? OR primary_name=?)",
                    (domain_id, stable, stable),
                ).fetchone()
                if row:
                    entity_id = row["entity_id"]
                    for alias in candidates:
                        db.execute(
                            "INSERT OR IGNORE INTO entity_aliases VALUES (?,?,?,?,?,?,?)",
                            (short_id("alias", entity_id, alias), entity_id, alias, "name", "extract", 0.9, now),
                        )
                    db.commit()
                    return {"entity_id": entity_id, "confidence": 1.0, "needs_review": False,
                            "reason": "stable-id-match", "aliases": candidates}
                entity_id = short_id("ent", domain_id, stable)
                db.execute(
                    "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
                    (entity_id, domain_id, None, stable, candidates[0] if candidates else stable,
                     self.schema.get("entity_types", ["unknown"])[0], now, now),
                )
                for alias in candidates:
                    db.execute(
                        "INSERT OR IGNORE INTO entity_aliases VALUES (?,?,?,?,?,?,?)",
                        (short_id("alias", entity_id, alias), entity_id, alias, "name", "extract", 0.9, now),
                    )
                db.commit()
                return {"entity_id": entity_id, "confidence": 1.0, "needs_review": False,
                        "reason": "stable-id-new", "aliases": candidates}

            # 无稳定标识：候选名精确匹配可复用；否则新建但标记低置信
            for name in candidates:
                row = db.execute(
                    "SELECT * FROM entities WHERE domain_id=? AND primary_name=?", (domain_id, name)
                ).fetchone()
                if row:
                    return {"entity_id": row["entity_id"], "confidence": 0.6,
                            "needs_review": True, "reason": "name-only-match", "aliases": candidates}
            primary = candidates[0] if candidates else "unknown_entity"
            entity_id = short_id("ent", domain_id, primary, "noid")
            db.execute(
                "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
                (entity_id, domain_id, None, None, primary, "unknown", now, now),
            )
            db.execute(
                """INSERT INTO review_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (short_id("rev", entity_id), "entity_resolution", "entity", entity_id,
                 "pending", 1, "ENTITY_AMBIGUOUS: no stable identifier", "{}", None, now, now, None),
            )
            db.commit()
            return {"entity_id": entity_id, "confidence": 0.3, "needs_review": True,
                    "reason": "no-stable-id", "aliases": candidates}
