"""联网搜索测试：解析器单测（离线 fixture）+ 收录链路（本地 fixture 页面）。

不依赖真实网络：Bing/搜狗解析用固定 HTML 片段验证；
收录动作拿本地启的 HTTP 服务当目标站，避免打真实站点。
"""
from __future__ import annotations

import sys
import tempfile
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app import websearch as ws
from websearch_lite.app.crawl import load_config
from websearch_lite.app.ingest import ingest_url
from websearch_lite.storage.sqlite_store import Store

BING_HTML = """
<html><body><ol id="b_results">
<li class="b_algo"><h2><a href="https://example.com/a">大模型 A 报告</a></h2>
  <p>这是关于大模型 A 的摘要内容。</p></li>
<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9i">大模型 B 报告</a></h2>
  <p>这是关于大模型 B 的摘要。</p></li>
<li class="b_algo"><h2><a href="https://example.com/a">重复链接</a></h2><p>应被去重。</p></li>
</ol></body></html>
"""

SOGOU_HTML = """
<html><body>
<div class="vrwrap"><h3><a href="https://example.com/s1">搜狗结果一</a></h3>
  <div class="str_info">搜狗摘要一</div></div>
<div class="vrwrap"><h3><a href="https://example.com/s2">搜狗结果二</a></h3>
  <div class="str_info">搜狗摘要二</div></div>
</body></html>
"""


class _Page(BaseHTTPRequestHandler):
    html = "<html><head><title>测试页面标题</title></head><body><article><p>正文第一段内容。</p>" \
           "<p>正文第二段内容。</p></article></body></html>"

    def log_message(self, *args):  # 静默
        return

    def do_GET(self):  # noqa: N802
        body = self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_bing_parser_extracts_results():
    parser = ws._BingParser()
    parser.feed(BING_HTML)
    assert len(parser.items) == 3
    assert parser.items[0]["title"] == "大模型 A 报告"
    assert "摘要" in parser.items[0]["snippet"]


def test_bing_url_unwrap():
    wrapped = "https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9i"
    assert ws._clean_bing_url(wrapped) == "https://example.com/b"
    assert ws._clean_bing_url("https://example.com/a") == "https://example.com/a"


def test_sogou_parser_extracts_results():
    parser = ws._SogouParser()
    parser.feed(SOGOU_HTML)
    assert len(parser.items) == 2
    assert parser.items[1]["title"] == "搜狗结果二"


def test_web_search_falls_back_when_first_engine_fails():
    original_bing, original_sogou = ws.search_bing, ws.search_sogou
    try:
        ws.search_bing = lambda q, limit=10: (_ for _ in ()).throw(RuntimeError("blocked"))
        ws.search_sogou = lambda q, limit=10: [{"title": "t", "url": "https://e.com", "snippet": "s", "engine": "sogou"}]
        out = ws.web_search("测试", limit=3)
        assert out["engine"] == "sogou" and out["results"]
        assert any("bing" in e for e in out["errors"])
    finally:
        ws.search_bing, ws.search_sogou = original_bing, original_sogou


def test_web_search_returns_empty_when_all_fail():
    original_bing, original_sogou = ws.search_bing, ws.search_sogou
    try:
        ws.search_bing = lambda q, limit=10: []
        ws.search_sogou = lambda q, limit=10: []
        out = ws.web_search("测试")
        assert out["engine"] is None and out["results"] == [] and out["errors"]
    finally:
        ws.search_bing, ws.search_sogou = original_bing, original_sogou


def test_ingest_url_stores_page_and_becomes_searchable():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tmp = tempfile.TemporaryDirectory()
    try:
        config = dict(load_config())
        config["database"] = str(Path(tmp.name) / "t.db")
        config["storage_root"] = tmp.name
        config["temp_root"] = str(Path(tmp.name) / "temp")
        (Path(tmp.name) / "temp").mkdir(parents=True, exist_ok=True)
        store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
        url = f"http://127.0.0.1:{port}/page"
        out = ingest_url(store, config, url=url)
        assert out["ok"] is True, out
        assert out["document_id"], out
        assert out["chars"] > 0
        hits = store.search("正文第一段")
        assert hits, "收录后本地检索应能命中"
        assert hits[0]["domain_id"] == "adhoc"
        # 重复收录同一 URL 不产生新版本
        again = ingest_url(store, config, url=url)
        assert again["ok"] is True and again["new_version"] is False
    finally:
        server.shutdown()
        server.server_close()
        tmp.cleanup()
