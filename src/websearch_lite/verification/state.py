"""事实验证状态机与可解释分量（V1.1 §8 / 评审决断 ⑤）。"""
from __future__ import annotations

# 合法迁移表：conflicting→verified 必须写 fact_conflicts 快照，不允许静默跳变。
TRANSITIONS: dict[str, set[str]] = {
    "unverified": {"single-source", "verified", "conflicting", "rejected", "stale"},
    "single-source": {"verified", "conflicting", "stale", "rejected", "single-source"},
    "verified": {"stale", "conflicting", "rejected", "verified"},
    "conflicting": {"verified", "single-source", "rejected", "stale", "conflicting"},
    "stale": {"verified", "conflicting", "rejected", "stale"},
    "rejected": set(),  # 终态
}

TERMINAL = {"rejected"}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise ValueError(f"ILLEGAL_VERIFICATION_TRANSITION: {current} -> {target}")


def decide_status(components: dict) -> str:
    """
    从可解释分量推导状态，不使用未校准乘积公式（V1.1 §8.4）。
    """
    if not components["extraction_quality"] == "passed":
        return "rejected"
    if components["freshness"] == "expired":
        return "stale"
    if components["evidence_consistency"] == "conflicting":
        return "conflicting"
    if components["independent_source_count"] >= 2 and components["authority_level"] == "authoritative":
        return "verified"
    if components["independent_source_count"] >= 2:
        return "verified"
    return "single-source"


def build_components(*, independent_source_count: int, authority_level: str,
                     evidence_consistency: str, freshness: str,
                     extraction_quality: str) -> dict:
    return {
        "independent_source_count": independent_source_count,
        "authority_level": authority_level,
        "evidence_consistency": evidence_consistency,
        "freshness": freshness,
        "extraction_quality": extraction_quality,
    }


def decision_reason(components: dict, status: str) -> str:
    return (f"{status}: independent_sources={components['independent_source_count']}, "
            f"authority={components['authority_level']}, consistency={components['evidence_consistency']}, "
            f"freshness={components['freshness']}, extraction={components['extraction_quality']}")
