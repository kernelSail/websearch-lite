# WebSearch Lite P2 验收记录（结构化抽取与实体解析）

时间：2026-11-06
基准：V1.1 §18 P2 / 评审补齐项 ①–④

## 1. 实现范围

| 项 | 实现 |
|---|---|
| 封闭 Schema | `domains/*/schema/procurement_v1.json`（6 字段）、`announcement_v1.json`（4 字段），含 `entity_resolution` 稳定标识规则 |
| 字段规范化 | `facts/normalize.py`：金额单位换算（元/万元/亿元）、13 位毫秒时间戳与中文日期、文本清洗、证据跨度 `find_span` |
| 实体解析 | `facts/entity_resolve.py`：稳定标识（项目编号 / 证券代码）优先；无稳定标识不自动合并，低置信进 `review_tasks`；别名表 `entity_aliases` |
| 分类器 | `facts/extractor.py` 的 `RuleClassifier`：封闭 Schema 规则抽取，输出固定字段 + `source_span` |
| 候选表 | 模型/规则输出先落 `raw_fact_candidates`（含 `validation_status` / `reject_reason`），再生成 `facts` / `fact_versions` / `fact_evidences` |
| 运行记录 | 全部任务、事实、候选引用 `processing_runs.run_id` |
| 事实状态 | 初始 `unverified`；状态机合法迁移在评审决断 ⑤ 已定义，P3 执行 |
| 幂等 | 同 `fact_id + normalized_value` 不重复建版本；重复抽取不产生重复事实 |
| 证据 | 每条事实绑定 `document_version_id + source_id + char_start/end + quoted_text + evidence_hash` |
| 流水线接入 | `config.p2.extract_on_ingest=true`，`crawl` 对新版本自动抽取；`cli extract` 可对已入库版本补跑 |
| CLI | `extract` / `eval2` / `facts`，`stats` 增加实体/事实/证据计数 |
| 评测 | `eval/p2_labels.json`（5 条草案样本）+ `eval/p2_eval.py`：字段级 P/R/F1、证据有效率、金额/日期规范化检查 |

## 2. 真实库端到端

```
python -m websearch_lite.cli extract
→ versions: 12, created: 20, failed: 0

stats:
  entities: 9, facts: 20, fact_versions: 20,
  fact_evidences: 20, raw_fact_candidates: 26, review_tasks: 0
```

9 个实体全部由稳定标识解析（政府采购 6 个 `project_code`、上市公司 3 个 `sec_code`），因此无低置信复核任务。所有事实状态 `unverified`（P3 验证）。

## 3. 字段级评测（eval2）

| 指标 | 值 |
|---|---:|
| overall Precision | 1.0 |
| overall Recall | 1.0 |
| overall F1 | 1.0 |
| TP / FP / FN | 15 / 0 / 0 |
| gov_procurement F1 | 1.0 |
| listed_announcement F1 | 1.0 |
| 证据有效率 | 1.0（15/15） |
| 规范化检查 | 6/6（万元/亿元/元、13 位时间戳、中文日期、非法日期） |
| 抽取错误 | 0 |

注：5 条草案样本仅作回归对照，不构成统计保证（V1.1 §14.5）；P3 前扩展标注集。

## 4. 单元测试

```
21 passed, 0 failed   （P0 7 + P1 6 + P2 8）
```

P2 覆盖：金额/日期规范化、证据跨度、规则字段抽取、事实+证据落库与幂等、无稳定标识进复核、评测报告、facts 列表。

## 5. 回归

| 项 | 结果 |
|---|---|
| P0 固定查询集 | 7/7 |
| P1 FTS5 vs Tantivy | 7/7 vs 7/7 |
| 索引一致性 | `missing_index=[]`、`version_mismatch=[]` |

## 6. 期间修正的问题

1. **元数据覆盖产生伪事实**：`metadata.sec_code` 无条件覆盖文本抽取结果，导致跨文档串号 → 改为「仅文本未抽到时兜底」。
2. **标注样本漏标 `company_name`**：把真实抽到的字段误记为 FP → 修正标注后 F1=1.0。
3. **`fact_evidences.source_id` 外键失败**：未传 metadata 时插空串 → 从 `document_versions` 反查 `source_id`。
4. **facts 包缺 `__init__.py`** → 补齐。
5. 控制台中文乱码为 PowerShell 输出编码，数据库内容正常（直接查库核验）。

## 7. 偏差与限制

- P2 分类器为**规则实现**，未接本地 LLM；按决断 4「本地优先、不可用降级规则」的降级路径执行。Schema 已封闭，未来替换模型不改下游。
- 补跑抽取用 `document_versions.snippet`（不长期存全文）作为文本，符合 C2；因此字段召回受 600 字截断限制，长文正文抽取待 P5 回源增强。
- 事实状态仍为 `unverified`，验证状态机与权威裁决属 P3。
- 标注样本 5 条，指标非统计保证。

## 8. 结论

P2 完成：封闭 Schema、字段规范化、证据跨度、实体解析、原始候选表、事实/版本/证据落库、流水线接入、CLI 与字段级评测均已实现并验收。

下一步为 P3（事实验证），未获指示不继续。
