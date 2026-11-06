# WebSearch Lite P3 验收记录（事实验证）

时间：2026-11-06
基准：V1.1 §8 / §18 P3，评审决断 ② ⑤

## 1. 实现范围

| 项 | 实现 |
|---|---|
| 转载识别 | `verification/source_graph.py`：simhash 近似 + 时间先后 + 同源线索；`from=原文, to=派生` |
| 独立源计数 | 「原文连通簇」个数；`repost/syndicated/original` 合并，`references/unknown` 不合并 |
| 关系持久化 | `source_relationships` 表，`to_db()` 写入，方向语义固定 |
| 验证状态机 | `verification/state.py`：合法迁移表，`rejected` 终态，`assert_transition` 拦截非法迁移 |
| 状态推导 | 可解释分量（独立源数 / 权威等级 / 一致度 / 时效 / 抽取质量），不用未校准乘积公式 |
| 冲突处理 | 同一 fact 不同值 → 双版本均 `conflicting`，写 `fact_conflicts` 快照（含被比较版本），不静默覆盖 |
| 权威裁决 | `resolve_conflict()`：写裁决理由/时间/裁决人，胜出版本 `verified`，关闭相关复核任务 |
| 复核队列 | 冲突、抽取质量失败、rejected 自动进 `review_tasks` |
| CLI | `verify` / `eval3` / `conflicts`（含 `--resolve --winner`）/ `review` |
| 评测 | `eval/p3_eval.py`：15 项规则层检查 + `scripts/p3_scenario.py` 双源冲突场景 |

## 2. 真实库端到端

```
python -m websearch_lite.cli verify
→ total: 20, single-source: 20, conflicting: 0, stale: 0, rejected: 0, errors: []
```

真实库每条事实仅 1 个证据源，全部 `single-source` 符合预期（无多源可验证）。

## 3. 双源 / 冲突场景（scripts/p3_scenario.py）

```
verify: independent_source_count=1（两源正文相同 → 识别为转载，合并为 1 独立源）
        authority=authoritative, consistency=consistent, freshness=current
        → single-source

加入第二个不同值版本后：
verify_all → conflicting: 2
conflicts: 2, reviews: 2（各版本保留快照，不静默覆盖）
resolve_conflict(winner=fv_2) → resolved
after: conflicting 1, verified 1
```

## 4. 评测

| 项 | 结果 |
|---|---|
| P3 规则层（eval3） | **15/15** |
| 单元测试 | **28 passed**（P0 7 + P1 6 + P2 8 + P3 7） |
| P0 固定查询集回归 | 7/7 |
| P1 FTS5 / Tantivy 回归 | 7/7 / 7/7 |
| P2 eval2 回归 | F1 1.0 |

`eval3` 覆盖：转载识别与方向、转载链合并为 1 独立源、无关文档单列、unknown 不合并、状态机合法/非法迁移、rejected 终态、双源 verified、单源 single-source、冲突/过期/抽取失败判定。

## 5. 期间修正

1. `tests/test_p3.py` 误查 `fact_versions.predicate`（该列在 `facts`）→ 删除无效 SQL。
2. `scripts/p3_scenario.py` 证据主键重复 → 改用唯一 id。
3. 内联 Python 引号转义失败 → 改为独立脚本文件。

## 6. 偏差与限制

- 转载识别基于 snippet（600 字截断），长文转载需 P5 回源增强。
- `authority_scope` 已存表但裁决尚未按「事实类型」限定权威范围（V1.1 §8.6 要求）；当前按 `sources.role` 全局判定，P4/P5 细化。
- 未接模型辅助转载/冲突判断，全部为确定性规则（符合「确定性优先」）。
- 真实库无多源与冲突样本，`verified` / `conflicting` 由构造场景验证，非真实数据分布（V1.1 §14.4 要求扩展标注集）。
- 事实状态机已定义但 `stale` 由 180 天阈值自动判定，未做领域级时效窗口配置。

## 7. 结论

P3 完成：转载识别、独立源计数、验证状态机、可解释分量、冲突快照与权威裁决、复核队列、CLI 与评测均已实现并验收。

下一步为 P4（统一查询与引用答案），未获指示不继续。
