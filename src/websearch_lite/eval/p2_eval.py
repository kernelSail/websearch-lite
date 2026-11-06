"""P2 字段级评测：Precision / Recall / F1、证据有效率、金额/日期错误发现。"""
from __future__ import annotations

import json
from pathlib import Path

from websearch_lite.facts.extractor import RuleClassifier, load_schema
from websearch_lite.facts.normalize import normalize_date, normalize_money
from websearch_lite.paths import find_project_root

ROOT = find_project_root()
LABELS = ROOT / "eval" / "p2_labels.json"


def load_labels() -> list[dict]:
    return json.loads(LABELS.read_text(encoding="utf-8"))["samples"]


def evaluate() -> dict:
    schemas = {d: load_schema(d) for d in ("gov_procurement", "listed_announcement")}
    tp = fp = fn = 0
    per_domain: dict[str, dict] = {}
    evidence_total = evidence_valid = 0
    money_errors = []

    for sample in load_labels():
        domain = sample["domain_id"]
        classifier = RuleClassifier(schemas[domain])
        result = classifier.classify(sample["text"], metadata=sample.get("metadata", {}))
        predicted = {k: v["normalized"] for k, v in result["fields"].items() if not v["error"]}
        expected = sample.get("expected", {})

        d = per_domain.setdefault(domain, {"tp": 0, "fp": 0, "fn": 0})
        for key, value in predicted.items():
            if key in expected and str(expected[key]) == str(value):
                d["tp"] += 1
                tp += 1
            else:
                d["fp"] += 1
                fp += 1
        for key in expected:
            if key not in predicted:
                d["fn"] += 1
                fn += 1

        for field in result["fields"].values():
            ev = field["evidence"]
            evidence_total += 1
            if ev["char_end"] > ev["char_start"] and ev["quoted_text"]:
                evidence_valid += 1
            if field["error"]:
                money_errors.append({"sample": sample["id"], "error": field["error"], "raw": field["raw"]})

    def prf(t, f, n):
        p = t / (t + f) if t + f else 0.0
        r = t / (t + n) if t + n else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
                "tp": t, "fp": f, "fn": n}

    domain_metrics = {k: prf(v["tp"], v["fp"], v["fn"]) for k, v in per_domain.items()}

    # 金额/日期规范化单元测试（确定性）
    norm_checks = {
        "money_wan": normalize_money("1,234.56 万元")["amount"] == 12345600.0,
        "money_yi": normalize_money("0.98 亿元")["amount"] == 98000000.0,
        "money_yuan": normalize_money("500 元")["amount"] == 500.0,
        "date_ms": normalize_date("1793849738000") == "2026-11-05",
        "date_cn": normalize_date("2026年11月5日") == "2026-11-05",
        "date_invalid": normalize_date("不是日期") is None,
    }

    return {
        "labels": str(LABELS),
        "overall": prf(tp, fp, fn),
        "per_domain": domain_metrics,
        "evidence_valid_rate": round(evidence_valid / max(1, evidence_total), 4),
        "evidence_total": evidence_total,
        "normalization_checks": norm_checks,
        "normalization_passed": sum(1 for v in norm_checks.values() if v),
        "extraction_errors": money_errors,
        "note": "样本为 5 条草案，指标仅用于回归对照，不构成统计保证（V1.1 §14.5）。",
    }
