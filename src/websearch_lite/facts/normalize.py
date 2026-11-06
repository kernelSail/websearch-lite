"""字段规范化：金额/单位/日期/文本。确定性优先，不依赖模型。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

MONEY_RE = re.compile(r"([0-9][0-9,.]*)\s*(亿元|万元|元)")
UNIT_TO_YUAN = {"亿元": 100_000_000, "万元": 10_000, "元": 1}


def normalize_money(raw: str) -> dict | None:
    match = MONEY_RE.search(raw)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    unit = match.group(2)
    return {
        "raw": raw.strip(),
        "amount": round(number * UNIT_TO_YUAN[unit], 2),
        "amount_display": number,
        "unit": unit,
        "currency": "CNY",
    }


def normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    # 毫秒时间戳
    if re.fullmatch(r"\d{13}", text):
        try:
            return datetime.fromtimestamp(int(text) / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return None
    patterns = [
        (r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", "%Y-%m-%d"),
        (r"(20\d{2})(\d{2})(\d{2})", "%Y-%m-%d"),
    ]
    for pattern, _ in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
            except ValueError:
                return None
    return None


def normalize_text(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw)).strip()
    text = re.sub(r"^[:：\s]+|[:：\s]+$", "", text)
    return text[:200]


def normalize_value(value_type: str, raw: Any) -> dict:
    """返回 {normalized, structured, unit, currency}。"""
    text = normalize_text(str(raw))
    if value_type == "money":
        money = normalize_money(text)
        if money is None:
            return {"normalized": text, "structured": None, "unit": None, "currency": None,
                    "error": "UNPARSEABLE_MONEY"}
        return {"normalized": str(money["amount"]), "structured": money,
                "unit": money["unit"], "currency": money["currency"], "error": None}
    if value_type == "enum":
        return {"normalized": text, "structured": None, "unit": None, "currency": None, "error": None}
    return {"normalized": text, "structured": None, "unit": None, "currency": None, "error": None}


def find_span(text: str, raw: str) -> tuple[int, int, str]:
    """证据跨度：精确匹配优先，否则返回最长公共片段前 200 字。"""
    if not raw:
        return 0, 0, ""
    pos = text.find(raw)
    if pos >= 0:
        return pos, pos + len(raw), raw[:200]
    # 退化：取包含关键词的一小段
    token = re.sub(r"\s+", "", raw)[:12]
    compact = re.sub(r"\s+", "", text)
    idx = compact.find(token)
    if idx >= 0:
        return idx, min(len(compact), idx + 80), compact[idx:idx + 80]
    return 0, min(len(text), 200), text[:200]
