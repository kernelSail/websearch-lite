"""P0 存储层：SQLite 权威数据 + FTS5 检索投影。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from ..common import dumps, loads, now_iso, sha256_text, short_id
from ..pipeline.extract import first_evidence


class Store:
    def __init__(self, db_path: str | Path, migrations_dir: str | Path) -> None:
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            sql_path = Path(migrations_dir) / "001_init.sql"
            db.executescript(sql_path.read_text(encoding="utf-8"))
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # ---------- 注册 ----------
    def register_domain(self, config: dict, config_path: str) -> None:
        now = now_iso()
        with closing(self._connect()) as db:
            db.execute(
                """INSERT INTO domains(domain_id,label,schema_version,config_path,storage_path,enabled,created_at,updated_at)
                   VALUES (?,?,?,?,?,1,?,?)
                   ON CONFLICT(domain_id) DO UPDATE SET label=excluded.label,
                     schema_version=excluded.schema_version, config_path=excluded.config_path,
                     storage_path=excluded.storage_path, updated_at=excluded.updated_at""",
                (config["id"], config.get("label", config["id"]), config.get("schema_version", "v1"),
                 config_path, config.get("storage_path", ""), now, now),
            )
            src = config["source"]
            db.execute(
                """INSERT INTO sources(source_id,domain_id,name,base_url,role,authority_scope_json,trust_weight,
                     robots_respect,rate_limit_rps,max_concurrency,enabled,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, base_url=excluded.base_url,
                     role=excluded.role, authority_scope_json=excluded.authority_scope_json,
                     trust_weight=excluded.trust_weight, rate_limit_rps=excluded.rate_limit_rps,
                     updated_at=excluded.updated_at""",
                (src["id"], config["id"], src["name"], src["base_url"], src.get("role", "reference"),
                 dumps(config.get("authority_scope", [])), float(config.get("trust_weight", 1.0)),
                 1 if config.get("robots_respect", True) else 0, float(config.get("rate_limit_rps", 1.0)),
                 int(config.get("max_concurrency", 1)), now, now),
            )
            db.commit()

    def list_domains(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                """SELECT d.*, s.source_id, s.name source_name, s.base_url, s.rate_limit_rps
                   FROM domains d JOIN sources s ON s.domain_id=d.domain_id
                   WHERE d.enabled=1 AND s.enabled=1"""
            ).fetchall()]

    # ---------- crawl 任务 ----------
    def enqueue_url(self, source_id: str, url: str, canonical_url: str, priority: int = 0) -> bool:
        now = now_iso()
        with closing(self._connect()) as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO crawl_tasks
                   (crawl_task_id,source_id,url,canonical_url,task_status,priority,discovered_at,updated_at)
                   VALUES (?,?,?,?, 'pending',?,?,?)""",
                (short_id("crawl", source_id, canonical_url), source_id, url, canonical_url, priority, now, now),
            )
            db.commit()
            return cur.rowcount > 0

    def next_crawl_tasks(self, source_id: str, limit: int) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT * FROM crawl_tasks WHERE source_id=? AND task_status IN ('pending','retry_wait')
                   ORDER BY priority DESC, discovered_at ASC LIMIT ?""", (source_id, limit),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE crawl_tasks SET task_status='running', updated_at=? WHERE crawl_task_id=?",
                           (now_iso(), row["crawl_task_id"]))
            db.commit()
            return [dict(r) for r in rows]

    def claim_crawl_tasks(self, source_id: str, due_ids: list[str], limit: int) -> list[dict]:
        """只认领 next_run_at 已到期的任务（P5 增量语义），未到期的保持 pending。"""
        if not due_ids:
            return []
        with closing(self._connect()) as db:
            placeholders = ",".join("?" for _ in due_ids)
            rows = db.execute(
                f"""SELECT * FROM crawl_tasks WHERE source_id=? AND task_status IN ('pending','retry_wait')
                    AND crawl_task_id IN ({placeholders})
                    ORDER BY priority DESC, discovered_at ASC LIMIT ?""",
                (source_id, *due_ids, limit),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE crawl_tasks SET task_status='running', updated_at=? WHERE crawl_task_id=?",
                           (now_iso(), row["crawl_task_id"]))
            db.commit()
            return [dict(r) for r in rows]

    def finish_crawl(self, task_id: str, status: str, *, http_status: int | None = None,
                     etag: str | None = None, last_modified: str | None = None,
                     error: str | None = None) -> None:
        with closing(self._connect()) as db:
            db.execute(
                """UPDATE crawl_tasks SET task_status=?, attempts=attempts+1, last_http_status=?,
                     etag=COALESCE(?,etag), last_modified=COALESCE(?,last_modified),
                     last_error=?, updated_at=? WHERE crawl_task_id=?""",
                (status, http_status, etag, last_modified, error, now_iso(), task_id),
            )
            db.commit()

    def update_source_health(self, source_id: str, success: bool, error: str | None = None) -> None:
        now = now_iso()
        with closing(self._connect()) as db:
            if success:
                db.execute("UPDATE sources SET last_success_at=?, consecutive_failures=0, updated_at=? WHERE source_id=?",
                           (now, now, source_id))
            else:
                db.execute(
                    """UPDATE sources SET last_failure_at=?, consecutive_failures=consecutive_failures+1,
                         updated_at=? WHERE source_id=?""", (now, now, source_id))
            db.commit()

    def source_health(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT source_id,name,last_success_at,last_failure_at,consecutive_failures,enabled FROM sources"
            ).fetchall()]

    # ---------- 文档入库（幂等 + 同 hash 复用） ----------
    def ingest(self, *, domain_id: str, source_id: str, url: str, canonical_url: str,
               title: str, text: str, published_at: str | None, fetched_at: str,
               http_status: int | None, etag: str | None, last_modified: str | None,
               extraction_status: str, metadata: dict, doc_type: str,
               run_id: str, snippet_limit: int = 600, evidence_limit: int = 400) -> dict:
        now = now_iso()
        content_hash = sha256_text(text)
        snippet = text[:snippet_limit]
        evidence = first_evidence(text, evidence_limit)
        meta = dict(metadata)
        meta["doc_type"] = doc_type
        meta["simhash"] = __import__("websearch_lite.common", fromlist=["simhash"]).simhash(text)

        with closing(self._connect()) as db:
            doc = db.execute("SELECT * FROM documents WHERE domain_id=? AND canonical_url=?",
                             (domain_id, canonical_url)).fetchone()
            if doc:
                document_id = doc["document_id"]
                db.execute("UPDATE documents SET updated_at=? WHERE document_id=?", (now, document_id))
            else:
                document_id = short_id("doc", domain_id, canonical_url)
                db.execute(
                    """INSERT INTO documents(document_id,domain_id,source_id,url,canonical_url,
                         lifecycle_status,created_at,updated_at) VALUES (?,?,?,?,?,'active',?,?)""",
                    (document_id, domain_id, source_id, url, canonical_url, now, now),
                )

            # 同 hash 复用（评审 ⑥）
            version = db.execute(
                "SELECT * FROM document_versions WHERE document_id=? AND content_hash=?",
                (document_id, content_hash),
            ).fetchone()
            if version:
                db.execute("UPDATE document_versions SET fetched_at=?, etag=COALESCE(?,etag), "
                           "last_modified=COALESCE(?,last_modified), http_status=? WHERE document_version_id=?",
                           (fetched_at, etag, last_modified, http_status, version["document_version_id"]))
                version_id = version["document_version_id"]
                new_version = False
            else:
                version_no = db.execute(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM document_versions WHERE document_id=?",
                    (document_id,),
                ).fetchone()[0]
                version_id = short_id("dv", document_id, content_hash)
                db.execute(
                    """INSERT INTO document_versions
                       (document_version_id,document_id,version_no,content_hash,title,snippet,published_at,
                        fetched_at,etag,last_modified,http_status,extraction_status,metadata_json,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_id, document_id, version_no, content_hash, title, snippet, published_at,
                     fetched_at, etag, last_modified, http_status, extraction_status, dumps(meta), now),
                )
                new_version = True

            db.execute("UPDATE documents SET current_version_id=? WHERE document_id=?", (version_id, document_id))

            # 检索投影（P0 FTS5）
            db.execute("DELETE FROM documents_index WHERE document_id=?", (document_id,))
            db.execute(
                """INSERT INTO documents_index
                   (doc_id,document_id,domain_id,source_id,title,snippet,entities,url,canonical_url,
                    published_at,fetched_at,document_version_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (short_id("idx", document_id), document_id, domain_id, source_id, title, snippet,
                 "", url, canonical_url, published_at, fetched_at, version_id),
            )

            # 证据短片段（长期只留这个，不留全文）
            if evidence and new_version:
                db.execute(
                    """INSERT OR IGNORE INTO fact_evidences
                       (evidence_id,fact_version_id,document_version_id,source_id,paragraph_index,
                        char_start,char_end,quoted_text,evidence_role,evidence_hash,created_at)
                       SELECT ?, fv.fact_version_id, ?, ?, 0, 0, ?, ?, 'context', ?, ?
                       FROM fact_versions fv WHERE fv.fact_version_id=?""",
                    (short_id("ev", version_id), version_id, source_id, len(evidence), evidence,
                     sha256_text(evidence), now, "__none__"),
                )
            for task_type in ("classify", "entity_resolve", "verify", "index"):
                db.execute(
                    """INSERT OR IGNORE INTO pipeline_tasks
                       (pipeline_task_id,document_version_id,task_type,task_status,idempotency_key,
                        run_id,created_at,updated_at) VALUES (?,?,?,'pending',?,?,?,?)""",
                    (short_id("pt", version_id, task_type), version_id, task_type,
                     f"{version_id}:{task_type}:v1", run_id, now, now),
                )
            db.commit()
            return {"document_id": document_id, "document_version_id": version_id,
                    "new_version": new_version, "content_hash": content_hash,
                    "evidence_chars": len(evidence)}

    # ---------- 检索 ----------
    def search(self, query: str, *, domain_id: str | None = None, limit: int = 20) -> list[dict]:
        trimmed = query.strip()
        with closing(self._connect()) as db:
            params: list[Any] = []
            clause = ""
            if domain_id:
                clause = " AND i.domain_id=?"
                params.append(domain_id)
            # FTS5 trigram 只索引 >=3 字符，2 字查询必须走 LIKE；
            # 长查询拆成 3-gram 片段做 OR，兼顾「中标（成交）结果公告」这类不连续短语。
            segments = [trimmed] if len(trimmed) <= 3 else [trimmed[i:i + 3] for i in range(len(trimmed) - 2)]
            segments = [s for s in dict.fromkeys(segments) if len(s) >= 3][:12]
            rows: list[sqlite3.Row] = []
            if segments:
                match = " OR ".join('"' + s.replace('"', '""') + '"' for s in segments)
                try:
                    rows = db.execute(
                        """SELECT i.* FROM documents_index i JOIN documents_fts f ON f.rowid=i.rowid
                           WHERE documents_fts MATCH ?""" + clause +
                        " ORDER BY i.fetched_at DESC LIMIT ?",
                        [match, *params, limit],
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            # LIKE 兜底：整词优先；若无命中，用 2-gram OR 扩大召回（trigram 无法覆盖
            # 「中标公告」vs「中标（成交）结果公告」这类不连续写法），再由上层按覆盖度重排。
            like_clause = " AND domain_id=?" if domain_id else ""
            like = "%" + trimmed.replace("%", "") + "%"
            like_rows = db.execute(
                """SELECT * FROM documents_index WHERE (title LIKE ? OR snippet LIKE ?)""" + like_clause +
                " ORDER BY fetched_at DESC LIMIT ?",
                [like, like, *params, limit],
            ).fetchall()
            if not like_rows and len(trimmed) >= 2:
                compact = "".join(trimmed.split())
                bigrams = list(dict.fromkeys(compact[i:i + 2] for i in range(len(compact) - 1)))[:8]
                if bigrams:
                    condition = " OR ".join("(title LIKE ? OR snippet LIKE ?)" for _ in bigrams)
                    like_args: list[Any] = []
                    for gram in bigrams:
                        like_args.extend([f"%{gram}%", f"%{gram}%"])
                    like_rows = db.execute(
                        """SELECT * FROM documents_index WHERE (""" + condition + ")""" + like_clause +
                        " ORDER BY fetched_at DESC LIMIT ?",
                        [*like_args, *params, limit * 3],
                    ).fetchall()
            merged = {r["doc_id"]: dict(r) for r in [*rows, *like_rows]}
            return list(merged.values())[:limit]

    def log_query(self, query: str, domains: list[str], result_ids: list[str], latency_ms: int) -> None:
        with closing(self._connect()) as db:
            db.execute("INSERT INTO query_log VALUES (?,?,?,?,?,?)",
                       (short_id("q", query, now_iso()), query, dumps(domains),
                        dumps(result_ids), latency_ms, now_iso()))
            db.commit()

    def stats(self) -> dict:
        with closing(self._connect()) as db:
            def count(sql, args=()):
                return db.execute(sql, args).fetchone()[0]
            indexed = count("SELECT COUNT(*) FROM documents_index")
            active = count("SELECT COUNT(*) FROM documents WHERE lifecycle_status='active'")
            return {
                "documents": count("SELECT COUNT(*) FROM documents"),
                "document_versions": count("SELECT COUNT(*) FROM document_versions"),
                "active_documents": active,
                "indexed_documents": indexed,
                "index_mismatch": max(0, active - indexed),
                "crawl_tasks": count("SELECT COUNT(*) FROM crawl_tasks"),
                "pipeline_tasks": count("SELECT COUNT(*) FROM pipeline_tasks"),
                "queries": count("SELECT COUNT(*) FROM query_log"),
                "review_tasks": count("SELECT COUNT(*) FROM review_tasks"),
                "entities": count("SELECT COUNT(*) FROM entities"),
                "facts": count("SELECT COUNT(*) FROM facts"),
                "fact_versions": count("SELECT COUNT(*) FROM fact_versions"),
                "fact_evidences": count("SELECT COUNT(*) FROM fact_evidences"),
                "raw_fact_candidates": count("SELECT COUNT(*) FROM raw_fact_candidates"),
            }

    def all_index_documents(self) -> list[dict]:
        """供 Tantivy 从 SQLite 权威数据重建检索投影（V1.1 §11.4）。"""
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM documents_index").fetchall()]

    def all_document_versions(self) -> list[dict]:
        """供 P2 补跑结构化抽取：用已存的 snippet 作为文本（不长期存全文）。"""
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                """SELECT dv.document_version_id, dv.title, dv.snippet, dv.published_at,
                          d.domain_id, d.source_id
                   FROM document_versions dv JOIN documents d ON d.document_id=dv.document_id
                   WHERE d.lifecycle_status='active'"""
            ).fetchall()]

    def list_facts(self, domain_id: str | None = None, limit: int = 50) -> list[dict]:
        with closing(self._connect()) as db:
            clause = " WHERE f.domain_id=?" if domain_id else ""
            params: list = [domain_id] if domain_id else []
            return [dict(r) for r in db.execute(
                """SELECT f.fact_id, f.domain_id, f.predicate, e.primary_name AS subject,
                          fv.normalized_value, fv.unit, fv.currency, fv.verification_status,
                          fv.schema_version, fv.created_at
                   FROM facts f JOIN entities e ON e.entity_id=f.subject_id
                   JOIN fact_versions fv ON fv.fact_id=f.fact_id""" + clause +
                " ORDER BY fv.created_at DESC LIMIT ?", [*params, limit]
            ).fetchall()]

    def list_conflicts(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM fact_conflicts ORDER BY created_at DESC")]

    def list_reviews(self, limit: int = 50) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM review_tasks WHERE status='pending' ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()]

    def source_relationships_count(self) -> int:
        with closing(self._connect()) as db:
            return db.execute("SELECT COUNT(*) FROM source_relationships").fetchone()[0]

    def verification_counts(self) -> dict:
        with closing(self._connect()) as db:
            return {row[0]: row[1] for row in db.execute(
                "SELECT verification_status,COUNT(*) FROM fact_versions GROUP BY verification_status")}

    def consistency(self) -> dict:
        with closing(self._connect()) as db:
            missing = db.execute(
                """SELECT d.document_id FROM documents d
                   WHERE d.lifecycle_status='active'
                     AND NOT EXISTS (SELECT 1 FROM documents_index i WHERE i.document_id=d.document_id)"""
            ).fetchall()
            stale = db.execute(
                """SELECT i.document_id FROM documents_index i
                   JOIN documents d ON d.document_id=i.document_id
                   WHERE d.current_version_id != i.document_version_id"""
            ).fetchall()
            return {"missing_index": [r[0] for r in missing],
                    "version_mismatch": [r[0] for r in stale]}
