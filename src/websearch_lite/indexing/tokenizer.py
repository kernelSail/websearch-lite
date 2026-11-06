"""中文分词：jieba 领域词典 + 标点/停用字过滤；缺失 jieba 时退化为 3-gram。

领域词典来自 domains/_shared/domain_dict.txt（离线维护，避免模型依赖）。
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    import jieba
except ImportError:  # 中文分词不可用时退化为字符 3-gram
    jieba = None

_DICT_PATH = Path(__file__).resolve().parents[3] / "domains" / "_shared" / "domain_dict.txt"
_LOADED = False
# 纯标点/空白 token 不进入索引，避免「（」「）」这类噪声占位
PUNCT_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
# 中文单字停用词：单独成词时无检索意义，却几乎在所有文档中出现，
# 会让 OR 回退命中全部文档（如「zzzz-不存在的关键词-xyz」曾召回所有公告）。
STOP_CHARS = set("的了是在和与及为对等不有中上下而或個个这那之其也就都还很最更")


def _load_domain_dict() -> None:
    """只加载一次领域词典（幂等）。"""
    global _LOADED
    if _LOADED or jieba is None:
        return
    if _DICT_PATH.exists():
        try:
            jieba.load_userdict(str(_DICT_PATH))
        except Exception:
            pass
    _LOADED = True


def _is_noise(token: str) -> bool:
    if not token or PUNCT_RE.match(token):
        return True
    # 单个中文字/汉字停用字丢弃；单个字母或数字保留（如型号 A1、3）
    if len(token) == 1 and token in STOP_CHARS:
        return True
    return False


def tokenize(text: str, *, for_search: bool = True) -> str:
    """中文分词：jieba + 领域词典，过滤标点与单字停用词。

    for_search=True 时用 jieba 的搜索模式（把长词再切出子词）：
    「股份回购」同时产出「股份」「回购」，从而能匹配「回购公司股份」这类语序不同的写法。
    """
    if not text:
        return ""
    if jieba is not None:
        _load_domain_dict()
        cut = jieba.cut_for_search(text) if for_search else jieba.cut(text)
        tokens = [t.strip() for t in cut]
        tokens = [t for t in tokens if not _is_noise(t)]
        # 去重但保序：搜索模式会产生重复子词
        return " ".join(dict.fromkeys(tokens))
    compact = "".join(text.split())
    return " ".join(compact[i:i + 3] for i in range(len(compact) - 2))

def query_tokens(text: str) -> list[str]:
    """
    查询用 token：在搜索模式分词基础上，去掉「可由其他 token 顺序拼接而成」的冗余整词。

    例：「中标公告」→ 中标 / 公告 / 中标公告，其中「中标公告」=「中标」+「公告」，
    若作为 AND 必需项会把「中标（成交）结果公告」排除，故查询时丢弃它。
    """
    tokens = tokenize(text).split()
    if len(tokens) <= 1:
        return tokens
    pool = list(dict.fromkeys(tokens))
    keep: list[str] = []
    for token in pool:
        others = [t for t in pool if t != token]
        # 判断 token 能否由 others 中若干词顺序拼接
        reachable = [False] * (len(token) + 1)
        reachable[0] = True
        for i in range(len(token)):
            if not reachable[i]:
                continue
            for other in others:
                if token.startswith(other, i):
                    reachable[i + len(other)] = True
        if reachable[len(token)]:
            continue
        keep.append(token)
    return keep or pool
