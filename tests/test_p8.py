"""P8 测试：领域词典分词、停用词过滤、搜索模式切分、查询整词去冗余、软路由。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.indexing.tokenizer import query_tokens, tokenize
from websearch_lite.query.coordinator import QueryCoordinator
from websearch_lite.storage.sqlite_store import Store

CFG = {"id": "gov_procurement", "label": "G", "schema_version": "procurement_v1",
       "storage_path": "x", "source": {"id": "s1", "name": "S1",
                                       "base_url": "https://a.cn/", "role": "authoritative"},
       "authority_scope": [], "trust_weight": 1.0}


def _store():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "t.db", ROOT / "migrations")
    store.register_domain(CFG, "x.json")
    return tmp, store


def test_domain_dictionary_keeps_terms_whole():
    # 搜索模式下整词与子词并存（整词供精确匹配，子词提召回）
    tokens = tokenize("可转换公司债券").split()
    assert "可转换公司债券" in tokens
    assert "丙交酯" in tokenize("年产3万吨丙交酯项目")


def test_stopwords_and_punctuation_removed():
    tokens = tokenize("中标（成交）结果公告").split()
    assert "（" not in tokens and "）" not in tokens
    assert tokenize("的") == ""


def test_search_mode_splits_compound_words():
    tokens = tokenize("股份回购").split()
    assert "股份" in tokens and "回购" in tokens


def test_query_tokens_drops_redundant_whole_word():
    assert query_tokens("中标公告") == ["中标", "公告"]
    assert query_tokens("股份回购") == ["股份", "回购"]
    assert query_tokens("医院") == ["医院"]


def test_stopword_only_query_returns_empty():
    assert tokenize("的了是在和") == ""
    assert query_tokens("的了是在和") == []


def test_soft_routing_keeps_all_domains():
    tmp, store = _store()
    try:
        with __import__("contextlib").closing(store._connect()) as db:
            db.execute("INSERT INTO domains VALUES (?,?,?,?,?,1,?,?)",
                       ("listed_announcement", "L", "v1", "x", "p", "2026-11-06", "2026-11-06"))
            db.commit()
        coordinator = QueryCoordinator(store, {"search_engine": "fts5"})
        routed = coordinator.route("中标公告")
        # 关键词命中域排首位，但不得排除其他域（同一查询可能跨域命中）
        assert routed[0] == "gov_procurement"
        assert "listed_announcement" in routed
    finally:
        tmp.cleanup()


def test_explicit_domain_filter_still_hard():
    tmp, store = _store()
    try:
        coordinator = QueryCoordinator(store, {"search_engine": "fts5"})
        assert coordinator.route("中标公告", {"domain_id": "listed_announcement"}) == ["listed_announcement"]
    finally:
        tmp.cleanup()
