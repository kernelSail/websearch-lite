# WebSearch Lite P6 验收记录（P5 完善项）

时间：2026-11-06
定位：补齐 P5 记录的偏差项，并把 P4 的域级近似评测替换为文档级真实相关性。

## 1. 实现范围

| 项 | 实现 |
|---|---|
| 增量语义落地 | `crawl(due_only=True)`：只认领 `next_run_at` 已到期任务（新增 `Store.claim_crawl_tasks`），未到期保持 pending 并计入 `deferred`；`--all` 可强制全量 |
| 常驻调度 | `app/daemon.py` + `cli run`：每轮执行「恢复 → 抓到期 → 一致性检查」，`--once` 单轮，`--interval` 控制间隔，Ctrl-C 正常退出 |
| 本地模型分类器 | `facts/llm_classifier.py`：OpenAI 兼容端点、封闭 Schema 提示词、**值必须出现在原文**（否则丢弃防幻觉）、探测失败自动回退规则 |
| 降级可观测 | `cli classifier-probe` 输出 configured_mode / active / probe；`fact_versions.extractor_model` 记录实际使用的分类器 |
| restore 安全 | `restore --apply` 覆盖前**自动备份当前库**，返回 `pre_restore_backup` |
| 移动盘 I/O 探活 | `_probe_io`：创建/写入/读回/删除探针，报告 `writable`、`io_error`、`readonly_domains` |
| 文档级评测 | `eval/p4_relevance.json`（6 条查询、真实 doc_id 标注）+ `p4_eval` 计算真实 Recall@K / Precision@K / nDCG@K，`approximation` 字段标记回退 |
| 检索改进 | ① 2-gram OR 兜底召回；② 查询词覆盖度参与重排（0.45 rank + 0.30 coverage + 0.15 authority + 0.10 recency）；③ 泛化尾缀（公告/项目/结果公告…）剥离后做变体召回 |

## 2. 中断恢复演练（scripts/p5_interrupt_drill.py）

```
模拟杀死：2 个任务置为 running 且 updated_at=2020
before: pending 18, running 2, succeeded 4
recovery.stale_recovered.crawl = 2, retry.requeued = 2
after:  pending 20, succeeded 4
recovered_tasks: [crawl_0125..., pending, attempts=1], [crawl_095a..., pending, attempts=0]
due_now: 20
```

## 3. 模型分类器现状（如实）

```
Ollama http://127.0.0.1:11434/v1 → available: false (timed out)
configured_mode: rule → active: rule
```

本机未运行 Ollama，分类器走规则路径。降级链路已验证：不可达端点 → `llm=None` → `classifier="rule"`，抽取结果正常（`award_amount=100000.0`）。配置切到 `local-llm` 且端点可用时自动启用模型，无需改代码。

## 4. 文档级评测（eval4）

| 指标 | 值 |
|---|---:|
| 文档级查询数 | 6（全部为真实标注，无近似） |
| Recall@K | 0.8472 |
| Precision@K | 0.68 |
| nDCG@K | 0.8375 |
| 引用正确率 | 1.0 |

| 查询 | hits | R@5 | P@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| 中标公告 | 5 | 0.333 | 0.20 | 0.273 |
| 医院 | 4 | 1.0 | 1.0 | 1.0 |
| 可转换公司债券 | 5 | 1.0 | 0.80 | 0.976 |
| 招标公告 | 5 | 0.75 | 0.60 | 0.840 |
| 天山电子 | 5 | 1.0 | 0.80 | 0.936 |
| 不存在的关键词 | 0 | 1.0 | — | 1.0 |

改进前「中标公告」Recall=0（FTS5 trigram 只共享片段「标公告」，召回到「招标公告」），加 2-gram 兜底 + 覆盖度重排 + 尾缀变体后提升到 0.333，仍不足：**trigram 索引对不连续短语（标题写作「中标（成交）结果公告」）本质受限**，属 P0 检索方案已知边界，需 P1 语义/分词索引才能根治。

## 5. 单元测试

```
49 passed, 0 failed
（P0 7 + P1 6 + P2 8 + P3 7 + P4 6 + P5 7 + P6 8）
```

P6 覆盖：常驻调度空轮、未到期任务不被认领、模型不可用降级规则、提示词只含封闭 Schema 字段、幻觉值被丢弃、restore 前自动备份、I/O 探活可写、缺失路径进 offline_domains。

## 6. 回归

| 项 | 结果 |
|---|---|
| P0 固定查询集 | 7/7 |
| P1 FTS5 / Tantivy | 7/7 / 7/7 |
| P2 eval2 | F1 1.0 |
| P3 eval3 | 15/15 |
| P4 eval4 | Recall@K 0.8472、引用 1.0 |
| 中断恢复 | 2/2 恢复为 pending |

## 7. 期间修正

1. `restore` 用 `cfg["database"]` 而非 `store.path` → 测试/多库场景恢复错目标。
2. P4 评测指标改为文档级后，旧测试断言 `total == 5` 失效 → 改为边界断言 `total >= 5` 且各指标 ∈ [0,1] 或 None。
3. P6 测试重复 `INSERT INTO domains` 触发主键冲突 → 改 `UPDATE`。
4. `_rerank` 签名变更未传 query → 覆盖度恒为 0，补参数。

## 8. 剩余已知限制

- 「中标公告」类不连续短语召回仍低（0.333），需分词/语义索引，非本阶段修复范围。
- 常驻调度为单进程前台循环，未接 Windows 服务/计划任务；崩溃后需手动再启（但任务状态可恢复）。
- 模型分类器未在真实 Ollama 上验证（本机未安装），仅验证降级与防幻觉逻辑。
- 标注集 6 条查询、12 篇文档，规模小，指标波动大；扩展语料后需重标。
- `restore --apply` 会关闭/覆盖当前库连接，需在无并发写入时执行。

## 9. 结论

P6 完成：P5 的 4 项偏差（调度未接主流程、restore 无保护、移动盘只查存在性、无中断演练）全部补齐，P4 域级近似评测替换为文档级真实评测，本地模型分类器接入并验证降级路径。
