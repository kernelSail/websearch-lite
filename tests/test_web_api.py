"""Web API 测试：直接测 Api 层（不起 HTTP 服务），覆盖读写端点契约。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite import server as server_mod


def _with_temp_api(fn):
    """把 Api 指向临时库，避免测试污染真实数据。"""
    tmp = tempfile.TemporaryDirectory()
    try:
        root = Path(tmp.name)
        db_path = root / "t.db"
        config = dict(server_mod.load_config())
        config["database"] = str(db_path)
        config["storage_root"] = str(root)
        config["temp_root"] = str(root / "temp")
        config["tantivy_root"] = str(root / "idx")
        (root / "temp").mkdir(parents=True, exist_ok=True)
        original_load = server_mod.load_config
        server_mod.load_config = lambda: config
        try:
            api = server_mod.Api()
            fn(api, config)
        finally:
            server_mod.load_config = original_load
    finally:
        tmp.cleanup()


def test_overview_shape():
    def run(api, _cfg):
        out = api.overview()
        for key in ("stats", "verification", "domains", "sources", "consistency", "engine", "classifier"):
            assert key in out, key
        assert isinstance(out["stats"]["documents"], int)
        assert out["consistency"]["missing_index"] == []

    _with_temp_api(run)


def test_empty_search_returns_no_results():
    def run(api, _cfg):
        out = api.search({"q": [""]})
        assert out["results"] == [] and out["answer"] == ""
        assert out["citations_valid"] is True

    _with_temp_api(run)


def test_search_after_ingest_keeps_raw_title():
    """回归：Tantivy 曾把分词结果当标题返回给前端。"""
    def run(api, _cfg):
        title = "河北省产品质量监督检验研究院重点工业产品检验检测设备更新项目公开招标中标公告"
        text = "项目编号：TEST-1\n项目名称：设备更新项目\n中标金额：100 万元"
        api.store.ingest(domain_id="gov_procurement", source_id="ccgp",
                         url="https://a.cn/1", canonical_url="https://a.cn/1",
                         title=title, text=text, published_at=None,
                         fetched_at="2026-11-06T00:00:00Z", http_status=200, etag=None,
                         last_modified=None, extraction_status="success", metadata={},
                         doc_type="procurement", run_id="r1")
        from websearch_lite.indexing.tantivy_port import TantivySearchPort
        port = TantivySearchPort(api.config["tantivy_root"])
        port.rebuild(api.store.all_index_documents())
        api.coordinator = server_mod.QueryCoordinator(api.store, api.config)
        out = api.search({"q": ["中标公告"], "limit": ["5"]})
        assert out["results"], out
        got = out["results"][0]["title"]
        assert got == title, f"标题被分词污染: {got!r}"
        assert " " not in got.strip()

    _with_temp_api(run)


def test_documents_and_detail():
    def run(api, _cfg):
        api.store.ingest(domain_id="gov_procurement", source_id="ccgp",
                         url="https://a.cn/2", canonical_url="https://a.cn/2",
                         title="测试公告", text="项目编号：T-2\n中标金额：1 万元",
                         published_at=None, fetched_at="2026-11-06T00:00:00Z",
                         http_status=200, etag=None, last_modified=None,
                         extraction_status="success", metadata={},
                         doc_type="procurement", run_id="r2")
        listing = api.documents({"limit": ["10"]})
        assert listing["total"] == 1
        doc_id = listing["documents"][0]["doc_id"]
        detail = api.document_detail(doc_id)
        assert detail["found"] is True
        assert detail["document"]["title"] == "测试公告"
        assert detail["versions"]

    _with_temp_api(run)


def test_write_actions_validate_input():
    def run(api, _cfg):
        bad = api.resolve_conflict({})
        assert bad["ok"] is False and "必填" in bad["error"]
        verify = api.action_verify({})
        assert verify["ok"] is True and "total" in verify["result"]

    _with_temp_api(run)


def test_facts_and_reviews_shape():
    def run(api, _cfg):
        assert "facts" in api.facts({"limit": ["5"]})
        assert "reviews" in api.reviews({})
        assert "conflicts" in api.conflicts()

    _with_temp_api(run)
