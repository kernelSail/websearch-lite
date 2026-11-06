# WebSearch Lite P4 验收记录（统一查询与引用答案）

时间：2026-11-06
基准：V1.1 §12 / §18 P4

## 1. 实现范围

| 项 | 实现 |
|---|---|
| QueryCoordinator | `query/coordinator.py`：域路由（关键词 hints + 显式 `--domain`）、结构化过滤、跨域合并、重排、答案 |
| 域内归一化 | 各域检索结果按 rank 归一化为 `rank_normalized`，不直接比较 BM25 原始分（V1.1 §12.3） |
| 结构化过滤 | `--domain / --since / --until / --status / source_id / title_contains` |
| 全局去重 | canonical URL + simhash 近似去重，跨合并结果生效 |
| 统一重排 | `0.6×归一化 rank + 0.25×来源权威权重 + 0.15×新近度` |
| 事实/证据约束 | `_attach_facts` 把每条结果关联的 fact_version（含 `verification_status`）挂到结果，答案只展示带来源的结果 |
| 引用完整性 | `_validate_citations`：每条结果必须有 URL + `document_version_id` |
| 答案生成 | 确定性带引用编号摘要（不做自由生成，避免编造）；冲突/单源事实在答案中标注状态 |
| CLI | `ask`（统一查询）、`eval4`（评测） |
| 评测 | `eval/p4_eval.py`：Recall@K（域级命中近似）、nDCG@K（二元增益）、引用正确率、延迟 |

## 2. 真实库端到端

```
python -m websearch_lite.cli ask "采购" --limit 3
→ 3 条带 [1][2][3] 引用结果，每条含 URL + 结构化事实（project_name / project_code，标注 single-source）

python -m websearch_lite.cli eval4
→ total 5, recall@k 1.0, ndcg@k 0.8, citation_accuracy 1.0, avg 16.2 ms
```

| 查询 | 命中 | Recall@K | nDCG@K | 引用完整 |
|---|---:|---:|---:|---|
| 采购 | 5 | 1.0 | 1.0 | ✅ |
| 中标 | 2 | 1.0 | 1.0 | ✅ |
| 证券代码 | 5 | 1.0 | 1.0 | ✅ |
| 公告 | 5 | 1.0 | 1.0 | ✅ |
| 不存在词 | 0 | 1.0（无相关域） | 0.0 | ✅ |

`ndcg@k` 均值 0.8 由「无结果查询」的 0.0 拉低，属预期。

## 3. 单元测试

```
34 passed, 0 failed   （P0 7 + P1 6 + P2 8 + P3 7 + P4 6）
```

P4 覆盖：关键词域路由、答案与引用结构、结构化过滤、引用完整性拒绝缺 URL、评测指标边界（0–1）、无命中答案无未绑定陈述。

## 4. 回归

| 项 | 结果 |
|---|---|
| P0 固定查询集 | 7/7 |
| P1 FTS5 / Tantivy | 7/7 / 7/7 |
| P2 eval2 | F1 1.0 |
| P3 eval3 | 15/15 |
| 索引一致性 | `missing_index=[]`、`version_mismatch=[]` |

## 5. 期间修正

1. `_apply_filters` 里 `until = filters.get("until"):` 语法错误（多余冒号）→ 修正。
2. nDCG@K 初版算出 >1（ideal 增益按相关域数量而非命中位置计算）→ 改为「前 K 命中中相关条数」的二元理想 DCG，并 clamp 到 [0,1]。

## 6. 偏差与限制

- Recall@K 为**域级命中近似**（无文档级标注池），P2 标注集扩展后需替换为真实相关性判定（V1.1 §14.2）。
- 答案生成为**确定性引用摘要**，未接 LLM 自由生成；V1.1 §12.4 的「答案生成 + 引用完整性检查」以规则方式满足，模型重排/生成属后续项。
- `ask "年度报告" --domain listed_announcement` 无命中：P0 巨潮采集的是 PDF 公告元数据与标题，未含年度报告正文，属**数据覆盖**问题而非查询层 bug；eval4 中该域「证券代码」「公告」均有命中。
- 域路由为关键词 hints，未做查询改写/同义扩展/语义召回（V1.1 §12.2 后续项）。
- 事实状态过滤 `--status` 过滤的是结果关联的事实，不过滤文档本身（文档仍返回，facts 列表被筛）。

## 7. 结论

P4 完成：统一查询、域内归一化合并、结构化过滤、全局去重、统一重排、事实/证据约束、带引用答案、引用完整性检查、CLI 与评测均已实现并验收。

下一步为 P5（增量调度、存储迁移和恢复），未获指示不继续。
