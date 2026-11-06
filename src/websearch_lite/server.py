"""本地只读/轻操作 HTTP API 服务（stdlib，无第三方依赖）。

路由：
  GET  /api/overview              统计、域、来源健康、一致性
  GET  /api/search?q=&domain=&limit=&status=
  GET  /api/documents?domain=&limit=&offset=&q=
  GET  /api/documents/<doc_id>    文档详情 + 证据 + 事实
  GET  /api/facts?domain=&status=&limit=
  GET  /api/conflicts
  GET  /api/reviews?limit=
  POST /api/conflicts/resolve     {conflict_id, winner, reason}
  POST /api/actions/crawl         {domain?, max_pages?}
  POST /api/actions/verify        {domain?}
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import crawl, load_config, load_domains, make_store, register_all
from websearch_lite.app.ingest import ingest_url
from websearch_lite.app.websearch import web_search
from websearch_lite.query.coordinator import QueryCoordinator
from websearch_lite.verification.verifier import Verifier

WEB_DIST = ROOT / "web" / "dist"

# 写操作串行执行，避免并发抓取/验证互相踩踏
_ACTION_LOCK = threading.Lock()


class Api:
    def __init__(self) -> None:
        self.config = load_config()
        self.domains = load_domains()
        self.store = make_store(self.config)
        register_all(self.store, self.domains)
        self.coordinator = QueryCoordinator(self.store, self.config)

    # ---------- 读 ----------
    def overview(self) -> dict:
        stats = self.store.stats()
        with closing(self.store._connect()) as db:
            domain_rows = [dict(r) for r in db.execute(
                """SELECT d.domain_id, d.label, d.enabled,
                          (SELECT COUNT(*) FROM documents dd WHERE dd.domain_id=d.domain_id) AS documents,
                          (SELECT COUNT(*) FROM facts f WHERE f.domain_id=d.domain_id) AS facts
                   FROM domains d ORDER BY d.domain_id"""
            ).fetchall()]
            recent = [dict(r) for r in db.execute(
                """SELECT doc_id, title, domain_id, canonical_url, fetched_at
                   FROM documents_index ORDER BY fetched_at DESC LIMIT 8"""
            ).fetchall()]
            last_runs = [dict(r) for r in db.execute(
                """SELECT run_id, code_version, schema_version, started_at, finished_at
                   FROM processing_runs ORDER BY started_at DESC LIMIT 6"""
            ).fetchall()]
        return {
            "stats": stats,
            "verification": self.store.verification_counts(),
            "domains": domain_rows,
            "sources": self.store.source_health(),
            "consistency": self.store.consistency(),
            "recent_documents": recent,
            "recent_runs": last_runs,
            "engine": self.config.get("search_engine", "fts5"),
            "classifier": self.config.get("classifier", {}).get("mode", "rule"),
        }

    def search(self, params: dict) -> dict:
        query = (params.get("q") or [""])[0].strip()
        if not query:
            return {"query": "", "results": [], "answer": "", "citations_valid": True,
                    "routed_domains": [], "latency_ms": 0,
                    "query_terms": {"specific": [], "generic": [], "df": {}}}
        limit = int((params.get("limit") or ["12"])[0])
        domain = (params.get("domain") or [""])[0] or None
        status = (params.get("status") or [""])[0] or None
        started = time.perf_counter()
        filters: dict[str, Any] = {}
        if domain:
            filters["domain_id"] = domain
        if status:
            filters["verification_status"] = status
        result = self.coordinator.search(query, filters=filters, limit=limit)
        latency = int((time.perf_counter() - started) * 1000)
        self.coordinator.log(query, result, latency)
        return {
            "query": query,
            "answer": result["answer"],
            "citations_valid": result["citations_valid"],
            "routed_domains": result["routed_domains"],
            "latency_ms": latency,
            "results": [
                {
                    "doc_id": r.get("doc_id"),
                    "document_version_id": r.get("document_version_id"),
                    "title": r.get("title"),
                    "url": r.get("canonical_url") or r.get("url"),
                    "snippet": r.get("snippet"),
                    "domain_id": r.get("domain_id"),
                    "fetched_at": r.get("fetched_at"),
                    "final_score": r.get("final_score"),
                    "term_coverage": r.get("term_coverage"),
                    "phrase_hit": r.get("phrase_hit"),
                    "facts": r.get("facts", []),
                }
                for r in result["results"]
            ],
            "query_terms": result.get("query_terms", {"specific": [], "generic": [], "df": {}}),
        }

    def documents(self, params: dict) -> dict:
        domain = (params.get("domain") or [""])[0] or None
        q = (params.get("q") or [""])[0].strip()
        limit = min(int((params.get("limit") or ["40"])[0]), 200)
        offset = int((params.get("offset") or ["0"])[0])
        clauses, args = [], []
        if domain:
            clauses.append("domain_id=?")
            args.append(domain)
        if q:
            clauses.append("(title LIKE ? OR snippet LIKE ?)")
            args.extend([f"%{q}%", f"%{q}%"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with closing(self.store._connect()) as db:
            total = db.execute("SELECT COUNT(*) FROM documents_index" + where, args).fetchone()[0]
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM documents_index" + where + " ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()]
        return {"total": total, "limit": limit, "offset": offset, "documents": rows}

    def document_detail(self, doc_id: str) -> dict:
        with closing(self.store._connect()) as db:
            index_row = db.execute("SELECT * FROM documents_index WHERE doc_id=?", (doc_id,)).fetchone()
            if not index_row:
                return {"found": False, "doc_id": doc_id}
            doc = dict(index_row)
            versions = [dict(r) for r in db.execute(
                "SELECT document_version_id,title,published_at,fetched_at,content_hash,extraction_status "
                "FROM document_versions WHERE document_id=?", (doc["document_id"],)
            ).fetchall()]
            evidences = [dict(r) for r in db.execute(
                """SELECT e.evidence_id, e.quoted_text, e.char_start, e.char_end, e.evidence_role,
                          f.predicate, fv.normalized_value, fv.verification_status, fv.fact_version_id,
                          en.primary_name AS subject
                   FROM fact_evidences e
                   JOIN fact_versions fv ON fv.fact_version_id=e.fact_version_id
                   JOIN facts f ON f.fact_id=fv.fact_id
                   JOIN entities en ON en.entity_id=f.subject_id
                   WHERE e.document_version_id IN
                         (SELECT document_version_id FROM document_versions WHERE document_id=?)""",
                (doc["document_id"],),
            ).fetchall()]
        return {"found": True, "document": doc, "versions": versions, "evidences": evidences}

    def facts(self, params: dict) -> dict:
        domain = (params.get("domain") or [""])[0] or None
        status = (params.get("status") or [""])[0] or None
        limit = min(int((params.get("limit") or ["60"])[0]), 300)
        clauses, args = [], []
        if domain:
            clauses.append("f.domain_id=?")
            args.append(domain)
        if status:
            clauses.append("fv.verification_status=?")
            args.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with closing(self.store._connect()) as db:
            rows = [dict(r) for r in db.execute(
                """SELECT f.fact_id, f.domain_id, f.predicate, e.primary_name AS subject,
                          fv.fact_version_id, fv.normalized_value, fv.unit, fv.currency,
                          fv.verification_status, fv.verification_summary, fv.schema_version,
                          fv.extractor_model, fv.created_at,
                          (SELECT COUNT(*) FROM fact_evidences fe WHERE fe.fact_version_id=fv.fact_version_id) AS evidence_count
                   FROM facts f
                   JOIN entities e ON e.entity_id=f.subject_id
                   JOIN fact_versions fv ON fv.fact_id=f.fact_id""" + where +
                " ORDER BY fv.created_at DESC LIMIT ?", [*args, limit]
            ).fetchall()]
        return {"facts": rows}

    def conflicts(self) -> dict:
        return {"conflicts": self.store.list_conflicts()}

    def reviews(self, params: dict) -> dict:
        limit = min(int((params.get("limit") or ["80"])[0]), 300)
        return {"reviews": self.store.list_reviews(limit=limit)}

    def websearch(self, params: dict) -> dict:
        """联网搜索：本地库没有的内容现场去搜。结果不入库，由用户点「收录」决定。"""
        query = (params.get("q") or [""])[0].strip()
        if not query:
            return {"query": "", "engine": None, "results": [], "latency_ms": 0, "errors": []}
        limit = min(int((params.get("limit") or ["10"])[0]), 20)
        return web_search(query, limit=limit)

    # ---------- 写（串行） ----------
    def action_ingest(self, body: dict) -> dict:
        """把联网搜索里的一条结果抓取入库，之后再搜本地库就能命中。"""
        url = str(body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "需要合法的 http(s) URL"}
        with _ACTION_LOCK:
            try:
                result = ingest_url(self.store, self.config, url=url, run_id="web-ingest")
                if result.get("ok"):
                    try:
                        from websearch_lite.indexing import build_search_port
                        port = build_search_port(self.config, self.store)
                        if hasattr(port, "upsert") and hasattr(port, "rebuild"):
                            port.rebuild(self.store.all_index_documents())
                    except Exception:
                        pass
                return result
            except Exception as error:
                return {"ok": False, "error": f"{type(error).__name__}: {error}"}

    # ---------- 写（串行） ----------
    def llm_client(self):
        cfg = self.config.get("llm", {})
        from websearch_lite.app.llm import LLMClient

        return LLMClient(
            endpoint=str(cfg.get("endpoint", "http://127.0.0.1:11434")),
            model=str(cfg.get("model", "qwen2.5:7b")),
            timeout=int(cfg.get("timeout", 300)),
        )

    def llm_probe(self) -> dict:
        try:
            return self.llm_client().probe()
        except Exception as error:
            return {"available": False, "error": str(error)}

    def research(self, body: dict, handler=None) -> dict:
        """深度检索：联网搜索 → 抓正文 → 模型总结。handler 存在时同时推 SSE 事件。"""
        question = str(body.get("question") or "").strip()
        if not question:
            return {"ok": False, "error": "question 必填"}
        max_sources = min(int(body.get("max_sources") or 5), 8)
        llm = self.llm_client()
        probe = llm.probe()
        if not probe.get("available"):
            return {"ok": False, "error": f"本地模型不可用：{probe.get('error') or '无已下载模型'}",
                    "probe": probe}
        if not probe.get("model_present"):
            return {"ok": False,
                    "error": f"模型 {llm.model} 未下载，请先执行 ollama pull {llm.model}",
                    "probe": probe}

        from websearch_lite.app.research import research as run_research

        def on_event(event: dict) -> None:
            if handler is not None:
                handler.sse(event)

        with _ACTION_LOCK:
            try:
                return run_research(question=question, store=self.store, config=self.config,
                                    llm=llm, max_sources=max_sources, on_event=on_event)
            except Exception as error:
                return {"ok": False, "error": f"{type(error).__name__}: {error}"}

    def resolve_conflict(self, body: dict) -> dict:
        conflict_id = str(body.get("conflict_id") or "")
        winner = str(body.get("winner") or "")
        if not conflict_id or not winner:
            return {"ok": False, "error": "conflict_id 与 winner 必填"}
        with _ACTION_LOCK:
            verifier = Verifier(self.store, self.config)
            return {"ok": True, **verifier.resolve_conflict(
                conflict_id, winner, decided_by="web-ui", reason=str(body.get("reason") or ""))}

    def action_crawl(self, body: dict) -> dict:
        domain = str(body.get("domain") or "")
        max_pages = body.get("max_pages")
        domains = dict(self.domains)
        if domain:
            domains = {k: v for k, v in domains.items() if k == domain}
        with _ACTION_LOCK:
            try:
                result = crawl(self.config, domains, self.store,
                               max_pages=int(max_pages) if max_pages else None, due_only=False)
                return {"ok": True, "result": result}
            except Exception as error:
                return {"ok": False, "error": f"{type(error).__name__}: {error}"}

    def action_verify(self, body: dict) -> dict:
        domain = str(body.get("domain") or "") or None
        with _ACTION_LOCK:
            try:
                verifier = Verifier(self.store, self.config)
                return {"ok": True, "result": verifier.verify_all(domain_id=domain)}
            except Exception as error:
                return {"ok": False, "error": f"{type(error).__name__}: {error}"}


class Handler(BaseHTTPRequestHandler):
    api: Api | None = None
    server_version = "websearch-lite/0.1"

    def log_message(self, fmt: str, *args) -> None:  # 静默：避免刷屏
        return

    # ---------- SSE ----------
    def start_sse(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.flush()

    def sse(self, payload: dict, event: str = "message") -> None:
        try:
            chunk = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- 工具 ----------
    def _send(self, status: int, payload: dict | bytes, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _serve_static(self, path: str) -> bool:
        if not WEB_DIST.exists():
            return False
        target = (WEB_DIST / path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB_DIST.resolve())):
            return False
        if not target.is_file():
            target = WEB_DIST / "index.html"
        if not target.is_file():
            return False
        suffix = target.suffix.lower()
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json"}
        self._send(200, target.read_bytes(), types.get(suffix, "application/octet-stream"))
        return True

    # ---------- 路由 ----------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                return self._route_api("GET", path, params, {})
            if path == "/" or path.startswith("/assets") or "." in Path(path).name:
                if self._serve_static(path):
                    return
            self._send(404, {"error": "not found"})
        except Exception:
            self._send(500, {"error": traceback.format_exc(limit=3)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            return self._route_api("POST", parsed.path, parse_qs(parsed.query), self._read_body())
        except Exception:
            self._send(500, {"error": traceback.format_exc(limit=3)})

    def _route_api(self, method: str, path: str, params: dict, body: dict) -> None:
        api = self.api
        assert api is not None
        if method == "GET":
            if path == "/api/overview":
                return self._send(200, api.overview())
            if path == "/api/search":
                return self._send(200, api.search(params))
            if path == "/api/documents":
                return self._send(200, api.documents(params))
            if path.startswith("/api/documents/"):
                return self._send(200, api.document_detail(path.rsplit("/", 1)[-1]))
            if path == "/api/facts":
                return self._send(200, api.facts(params))
            if path == "/api/conflicts":
                return self._send(200, api.conflicts())
            if path == "/api/reviews":
                return self._send(200, api.reviews(params))
            if path == "/api/websearch":
                return self._send(200, api.websearch(params))
            if path == "/api/llm":
                return self._send(200, api.llm_probe())
        else:
            if path == "/api/research":
                # 流式：先推阶段事件，最后推完整结果
                self.start_sse()
                result = api.research(body, handler=self)
                self.sse(result, event="done")
                return
            if path == "/api/conflicts/resolve":
                return self._send(200, api.resolve_conflict(body))
            if path == "/api/actions/crawl":
                return self._send(200, api.action_crawl(body))
            if path == "/api/actions/verify":
                return self._send(200, api.action_verify(body))
            if path == "/api/actions/ingest":
                return self._send(200, api.action_ingest(body))
        return self._send(404, {"error": "unknown api"})

    # ---------- 静态资源 MIME 兜底 ----------
    def guess_type(self, path: str) -> str:
        return "application/octet-stream"


def serve(host: str = "127.0.0.1", port: int = 8765) -> int:
    Handler.api = Api()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(json.dumps({"serving": f"http://{host}:{port}", "web_dist": str(WEB_DIST),
                      "web_built": WEB_DIST.exists()}, ensure_ascii=False), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="websearch-lite-server", description="本地控制台 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    sys.exit(serve(host=args.host, port=args.port))
