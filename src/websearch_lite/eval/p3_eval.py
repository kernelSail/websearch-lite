"""P3 评测：转载识别、独立源计数、状态机迁移、冲突不静默覆盖。"""
from __future__ import annotations

from ..verification.source_graph import SourceGraph
from ..verification.state import assert_transition, can_transition, decide_status, build_components


def evaluate() -> dict:
    checks: dict[str, bool] = {}

    # 1) 转载识别：两段高度相似文本，较早者为原文
    g = SourceGraph()
    g.add_node("a", fetched_at="2026-11-01T00:00:00Z", source_id="s1",
               text="某某医院设备采购项目中标金额为人民币一千二百万元整公告全文")
    g.add_node("b", fetched_at="2026-11-02T00:00:00Z", source_id="s2",
               text="某某医院设备采购项目中标金额为人民币一千二百万元整公告全文")
    created = g.detect_reposts()
    checks["repost_detected"] = created == 1
    checks["repost_direction_earlier_is_original"] = any(
        frm == "a" and to == "b" and kind == "repost"
        for frm, edges in g.edges.items() for to, kind, _, _ in edges
    )

    # 2) 独立源计数：转载链合并为一簇；无关文档单列；unknown 不合并
    count, clusters = g.independent_clusters(["a", "b"])
    checks["repost_chain_counts_as_one"] = count == 1
    g.add_node("c", fetched_at="2026-11-03T00:00:00Z", source_id="s3", text="完全不同的另一条公告内容")
    count2, _ = g.independent_clusters(["a", "b", "c"])
    checks["unrelated_doc_counts_separately"] = count2 == 2
    g2 = SourceGraph()
    g2.add_node("x", fetched_at="2026-11-01T00:00:00Z", source_id="s1", text="相同内容")
    g2.add_node("y", fetched_at="2026-11-02T00:00:00Z", source_id="s2", text="相同内容")
    g2.add_relation("x", "y", "unknown", 0.3)
    count3, _ = g2.independent_clusters(["x", "y"])
    checks["unknown_relation_not_merged"] = count3 == 2

    # 3) 状态机
    checks["unverified_to_verified_ok"] = can_transition("unverified", "verified")
    checks["verified_to_conflicting_ok"] = can_transition("verified", "conflicting")
    checks["conflicting_to_verified_ok"] = can_transition("conflicting", "verified")
    checks["rejected_terminal"] = not can_transition("rejected", "verified")
    try:
        assert_transition("rejected", "verified")
        checks["illegal_transition_rejected"] = False
    except ValueError:
        checks["illegal_transition_rejected"] = True

    # 4) 状态推导：不用未校准乘积
    comp = build_components(independent_source_count=2, authority_level="authoritative",
                            evidence_consistency="consistent", freshness="current",
                            extraction_quality="passed")
    checks["two_independent_sources_verified"] = decide_status(comp) == "verified"
    comp1 = {**comp, "independent_source_count": 1}
    checks["single_source_single_status"] = decide_status(comp1) == "single-source"
    comp_conf = {**comp, "evidence_consistency": "conflicting"}
    checks["conflicting_detected"] = decide_status(comp_conf) == "conflicting"
    comp_stale = {**comp, "freshness": "expired"}
    checks["stale_detected"] = decide_status(comp_stale) == "stale"
    comp_bad = {**comp, "extraction_quality": "failed"}
    checks["bad_extraction_rejected"] = decide_status(comp_bad) == "rejected"

    return {
        "checks": checks,
        "passed": sum(1 for v in checks.values() if v),
        "total": len(checks),
        "note": "P3 规则层离线评测；真实冲突样本需在标注集扩展后补充（V1.1 §14.4）。",
    }
