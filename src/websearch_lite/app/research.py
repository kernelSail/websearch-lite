"""深度检索：联网搜索 → 抓取正文 → 相关性筛选 → 模型总结（带引用）。

一条链路解决「问一个问题，系统自己找资料并总结」。
每一步都产出可观测的阶段事件，供前端流式展示。
"""
from __future__ import annotations

import re
import time
from typing import Callable, Iterator

from ..crawler.adapters import build_adapter
from ..crawler.fetcher import Fetcher
from ..indexing.tokenizer import tokenize
from .llm import LLMClient, LLMError, SYSTEM_PROMPT, build_research_prompt, extract_citations
from .websearch import web_search

# 抓取阶段上限：串行抓取，礼貌速率
MAX_SOURCES = 1  # CPU 推理慢，先保证单篇能出结果
MAX_LOCAL_SOURCES = 1  # 本地库只补充 1 篇，避免把 prompt 撑大
MAX_CHARS_PER_SOURCE = 450  # CPU 推理下控制 prompt 体积，避免单次请求过久

# 问句里的疑问/语气成分：直接整句丢给搜索引擎会被当成查某个单字
QUESTION_NOISE = (
    "有哪些", "有什么", "是什么", "怎么样", "怎么", "如何", "为什么", "为什么", "是否",
    "哪些", "哪个", "多少", "能不能", "可不可以", "介绍一下", "告诉我", "请问",
    "的", "了", "吗", "呢", "吧", "啊", "呀", "？", "?", "。", "，", ",",
)


def build_search_query(question: str, *, max_terms: int = 5) -> str:
    """
    从自然语言问句里抽检索词。
    「大模型最新的进展有哪些？」→「大模型 最新 进展」
    否则 Bing 会把整句当成长尾词，甚至退化成查单字。
    """
    text = question.strip()
    for noise in QUESTION_NOISE:
        text = text.replace(noise, " ")
    tokens = [t for t in tokenize(text).split() if len(t) >= 2]
    # 去重保序，最多取 max_terms 个
    picked = list(dict.fromkeys(tokens))[:max_terms]
    return " ".join(picked) if picked else question.strip()


def _relevance(text: str, question: str) -> float:
    """问题词在正文中的覆盖比例，用于过滤完全不相关的页面。"""
    q_tokens = [t for t in tokenize(question).split() if len(t) >= 2]
    if not q_tokens:
        return 0.0
    body = text[:8000]
    hit = sum(1 for t in q_tokens if t in body)
    return hit / len(q_tokens)


def _summarize_local(store, question: str, limit: int = MAX_LOCAL_SOURCES) -> list[dict]:
    """本地库命中作为补充资料（已结构化、带验证状态）。"""
    try:
        hits = store.search(question, limit=limit)
    except Exception:
        return []
    out = []
    for hit in hits:
        out.append({
            "title": hit.get("title") or "",
            "url": hit.get("canonical_url") or hit.get("url") or "",
            "text": (hit.get("snippet") or "")[:200],
            "origin": "local",
            "domain_id": hit.get("domain_id"),
        })
    return out


def research(*, question: str, store, config: dict, llm: LLMClient,
             max_sources: int = MAX_SOURCES,
             on_event: Callable[[dict], None] | None = None) -> dict:
    """
    同步执行完整链路，返回 {answer, sources, citations, stages, timings}。
    on_event 用于把阶段进度推给前端。
    """
    started = time.perf_counter()
    stages: list[dict] = []

    def emit(stage: str, **extra) -> None:
        event = {"stage": stage, "elapsed_ms": int((time.perf_counter() - started) * 1000), **extra}
        stages.append(event)
        if on_event:
            on_event(event)

    # 1) 联网搜索（先把问句压成检索词，否则引擎会把整句当长尾词）
    search_query = build_search_query(question)
    emit("search_start", query=question, search_query=search_query)
    found = web_search(search_query, limit=max_sources * 2)
    emit("search_done", engine=found.get("engine"), count=len(found.get("results", [])),
         search_query=search_query, errors=found.get("errors", []))
    if not found.get("results"):
        return {"answer": "联网搜索没有返回结果，无法总结。", "sources": [],
                "citations": [], "stages": stages, "ok": False,
                "error": "WEB_SEARCH_EMPTY", "errors": found.get("errors", [])}

    # 2) 抓取正文
    fetcher = Fetcher(config)
    adapter = build_adapter("generic")
    sources: list[dict] = []
    emit("fetch_start", total=min(max_sources, len(found["results"])))
    for item in found["results"]:
        if len(sources) >= max_sources:
            break
        url = item.get("url") or ""
        if not url.startswith("http"):
            continue
        try:
            result = fetcher.fetch(url, rps=1.0, respect_robots=True, base_url=url)
            if result.error or not result.body:
                continue
            html = result.body.decode("utf-8", errors="replace")
            content = adapter.extract_content(html, url, [])
            text = content.get("text") or ""
            if len(text) < 120:
                continue
            score = _relevance(text, question)
            if score < 0.34:  # 至少命中 1/3 的问题词，滤掉「3D 模型下载」这类歧义噪声
                continue
            sources.append({
                "title": content.get("title") or item.get("title") or url,
                "url": url,
                "text": text[:MAX_CHARS_PER_SOURCE * 2],
                "snippet": (item.get("snippet") or "")[:200],
                "origin": "web",
                "relevance": round(score, 3),
                "chars": len(text),
            })
            emit("fetch_one", url=url, ok=True, relevance=round(score, 3))
        except Exception as error:
            emit("fetch_one", url=url, ok=False, error=f"{type(error).__name__}: {str(error)[:80]}")
    emit("fetch_done", fetched=len(sources))

    # 3) 本地库补充（已采集的结构化内容）
    local = _summarize_local(store, question)
    if local:
        known = {s["url"] for s in sources}
        for item in local:
            if item["url"] and item["url"] not in known:
                sources.append(item)
        emit("local_done", added=len([s for s in sources if s.get("origin") == "local"]))

    if not sources:
        return {"answer": "抓到的页面都不相关，或正文抽取失败，无法总结。", "sources": [],
                "citations": [], "stages": stages, "ok": False,
                "error": "NO_USABLE_SOURCES"}

    # 4) 模型总结
    emit("llm_start", model=llm.model, sources=len(sources))
    prompt = build_research_prompt(question, sources, max_chars_per_source=MAX_CHARS_PER_SOURCE)
    try:
        answer = llm.chat(prompt, system=SYSTEM_PROMPT, temperature=0.2, max_tokens=1200)
    except LLMError as error:
        emit("llm_error", error=str(error))
        return {"answer": f"模型调用失败：{error}", "sources": sources, "citations": [],
                "stages": stages, "ok": False, "error": "LLM_ERROR"}
    citations = extract_citations(answer)
    valid = [c for c in citations if 1 <= c <= len(sources)]
    invalid = [c for c in citations if c not in valid]
    emit("llm_done", chars=len(answer), citations=citations, invalid_citations=invalid)

    return {
        "answer": answer,
        "sources": [
            {"index": i + 1, "title": s.get("title"), "url": s.get("url"),
             "origin": s.get("origin"), "chars": s.get("chars"), "relevance": s.get("relevance"),
             "domain_id": s.get("domain_id")}
            for i, s in enumerate(sources)
        ],
        "citations": citations,
        "invalid_citations": invalid,
        "stages": stages,
        "ok": True,
        "model": llm.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
