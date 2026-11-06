"""本地 LLM 分类器（OpenAI 兼容端点），规则降级 + 可用性探测。

设计约束（V1.1 §7 / 决断 4）：
- 只输出封闭 Schema 内的字段，额外字段丢弃；
- 模型不可用/超时/解析失败时**回退规则抽取**，不阻塞流水线；
- 不依赖任何付费第三方 API；端点由 config 指定，默认指向本机 Ollama。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from .normalize import find_span, normalize_value

TIMEOUT_SECONDS = 20


def build_prompt(schema: dict, text: str) -> str:
    predicates = [
        {"predicate": f["predicate"], "type": f.get("value_type", "text"),
         **({"enum": f["enum"]} if f.get("enum") else {})}
        for f in schema.get("facts", [])
    ]
    return (
        "你是结构化信息抽取器。只从下面文本中抽取事实，不要编造。\n"
        f"允许的谓词（仅限这些）：{json.dumps(predicates, ensure_ascii=False)}\n"
        "输出严格 JSON：{\"fields\":[{\"predicate\":\"...\",\"value\":\"原文片段\"}]}\n"
        "没有抽到的谓词请不要输出。value 必须是文本中出现的原文片段。\n\n"
        f"文本：\n{text[:3000]}"
    )


class LocalLLMClassifier:
    name = "local-llm"

    def __init__(self, schema: dict, config: dict) -> None:
        self.schema = schema
        cfg = config.get("classifier", {})
        self.endpoint = str(cfg.get("local_endpoint", "http://127.0.0.1:11434/v1")).rstrip("/")
        self.model = str(cfg.get("model", "qwen2.5:7b"))

    # ---------- 可用性探测 ----------
    def probe(self) -> dict:
        try:
            req = urllib.request.Request(self.endpoint + "/models", headers={"accept": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
            models = [m.get("id") for m in data.get("data", [])]
            return {"available": True, "endpoint": self.endpoint, "models": models[:10]}
        except Exception as error:
            return {"available": False, "endpoint": self.endpoint, "error": str(error)[:200]}

    # ---------- 抽取 ----------
    def classify(self, text: str, *, metadata: dict | None = None) -> dict:
        metadata = metadata or {}
        allowed = {f["predicate"]: f for f in self.schema.get("facts", [])}
        payload = self._call(text)
        fields: dict[str, dict] = {}
        for item in payload:
            predicate = str(item.get("predicate", ""))
            value = str(item.get("value", "")).strip()
            spec = allowed.get(predicate)
            if not spec or not value:
                continue
            # 值必须在原文出现，否则视为幻觉丢弃
            if value not in text:
                continue
            normalized = normalize_value(spec.get("value_type", "text"), value)
            char_start, char_end, quote = find_span(text, value)
            fields[predicate] = {
                "raw": value,
                "normalized": normalized["normalized"],
                "structured": normalized["structured"],
                "unit": normalized["unit"],
                "currency": normalized["currency"],
                "error": normalized["error"],
                "evidence": {"char_start": char_start, "char_end": char_end, "quoted_text": quote},
                "source": "local-llm",
            }
        return {
            "schema_id": self.schema["schema_id"],
            "fields": fields,
            "entity_fields": {k: v["normalized"] for k, v in fields.items()},
            "model": self.model,
        }

    def _call(self, text: str) -> list[dict]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": build_prompt(self.schema, text)}],
            "temperature": 0,
            "max_tokens": 600,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            self.endpoint + "/chat/completions", data=body,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        match = __import__("re").search(r"\{.*\}", content, __import__("re").S)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            return []
        items = parsed.get("fields", []) if isinstance(parsed, dict) else []
        return items if isinstance(items, list) else []
