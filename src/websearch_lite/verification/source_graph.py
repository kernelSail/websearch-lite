"""转载关系检测与独立来源计数（V1.1 §8.3 / 评审决断 ②）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..common import dumps, hamming, now_iso, short_id, simhash


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class SourceGraph:
    """文档版本之间的 from(原文) → to(派生) 关系图。"""

    def __init__(self) -> None:
        self.edges: dict[str, list[tuple[str, str, float, dict]]] = {}
        self.nodes: dict[str, dict] = {}

    def add_node(self, document_version_id: str, *, fetched_at: str | None = None,
                 source_id: str | None = None, text: str = "") -> None:
        self.nodes[document_version_id] = {
            "fetched_at": fetched_at,
            "source_id": source_id,
            "simhash": simhash(text),
        }
        self.edges.setdefault(document_version_id, [])

    def add_relation(self, from_id: str, to_id: str, kind: str,
                     confidence: float, evidence: dict | None = None) -> None:
        """from = 原文（更早/更完整/署名源），to = 派生。"""
        if from_id == to_id or from_id not in self.nodes or to_id not in self.nodes:
            return
        self.edges[from_id].append((to_id, kind, confidence, evidence or {}))

    def detect_reposts(self, *, threshold: int = 6) -> int:
        """自动识别转载：正文近似 + 时间先后 + 同源/署名线索。"""
        ids = list(self.nodes)
        created = 0
        for i, a_id in enumerate(ids):
            a = self.nodes[a_id]
            for b_id in ids[i + 1:]:
                b = self.nodes[b_id]
                distance = hamming(a["simhash"], b["simhash"])
                if distance > threshold:
                    continue
                ta, tb = parse_time(a["fetched_at"]), parse_time(b["fetched_at"])
                if ta and tb and ta > tb:
                    a_id, b_id = b_id, a_id
                    a, b = b, a
                elif not ta or not tb:
                    # 时间不可判：仅当同源才按 id 顺序，否则标 unknown 不自动建转载
                    if a["source_id"] != b["source_id"]:
                        continue
                confidence = round(1.0 - distance / max(1, threshold + 2), 3)
                evidence = {"simhash_distance": distance, "reason": "near-duplicate-text"}
                self.add_relation(a_id, b_id, "repost", confidence, evidence)
                created += 1
        return created

    def independent_clusters(self, document_version_ids: list[str]) -> tuple[int, list[dict]]:
        """
        独立来源数 = 「原文连通簇」个数。
        - repost/syndicated/original 关系把文档连到同一簇；
        - references/unknown 不合并（未知关系不能默认算独立，也不默认同源，保守单列）。
        """
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        included = set(document_version_ids)
        for from_id, edges in self.edges.items():
            for to_id, kind, _, _ in edges:
                if from_id in included and to_id in included and kind in ("original", "repost", "syndicated"):
                    union(from_id, to_id)

        clusters: dict[str, list[str]] = {}
        for doc_id in document_version_ids:
            clusters.setdefault(find(doc_id), []).append(doc_id)
        return len(clusters), [{"root": root, "members": members} for root, members in clusters.items()]

    def to_db(self, store, run_id: str | None = None) -> int:
        """把关系写入 source_relationships 表。"""
        now = now_iso()
        count = 0
        with __import__("contextlib").closing(store._connect()) as db:
            for from_id, edges in self.edges.items():
                for to_id, kind, confidence, evidence in edges:
                    rid = short_id("rel", from_id, to_id, kind)
                    cur = db.execute(
                        """INSERT OR IGNORE INTO source_relationships
                           (relationship_id,from_document_version_id,to_document_version_id,
                            relationship_type,confidence,evidence_json,reviewed,created_at)
                           VALUES (?,?,?,?,?,?,0,?)""",
                        (rid, from_id, to_id, kind, confidence, dumps(evidence), now),
                    )
                    count += cur.rowcount
            db.commit()
        return count


def build_source_graph(store) -> SourceGraph:
    """从 SQLite 装载文档版本与已登记关系。"""
    graph = SourceGraph()
    with __import__("contextlib").closing(store._connect()) as db:
        for row in db.execute(
            """SELECT dv.document_version_id, dv.fetched_at, dv.snippet, d.source_id
               FROM document_versions dv JOIN documents d ON d.document_id=dv.document_id"""
        ):
            graph.add_node(row["document_version_id"], fetched_at=row["fetched_at"],
                           source_id=row["source_id"], text=row["snippet"] or "")
        for row in db.execute(
            "SELECT from_document_version_id,to_document_version_id,relationship_type,confidence,evidence_json FROM source_relationships"
        ):
            graph.add_relation(row["from_document_version_id"], row["to_document_version_id"],
                               row["relationship_type"], row["confidence"] or 0.0,
                               __import__("websearch_lite.common", fromlist=["loads"]).loads(row["evidence_json"], {}))
    return graph
