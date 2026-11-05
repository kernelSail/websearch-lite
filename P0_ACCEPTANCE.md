# WebSearch Lite P0 验收记录

时间：2026-11-05
环境：Python 3.12.14 / SQLite 3.53.1（FTS5 trigram）/ Windows 11 / i7-9750H / 32GB / SSD

## 1. 前置探测（V1.1 §19 决断 1、2）

| 域 | 来源 | robots | 可达 | 结论 |
|---|---|---|---|---|
| gov_procurement | ccgp.gov.cn | 404 → 无禁止规则 | HTTP 200 | PASS |
| listed_announcement | cninfo.com.cn | 404 → 无禁止规则 | HTTP 200 | PASS |

## 2. 采集结果（--max-pages 6，礼貌速率 1 rps）

| 域 | 发现 | 抓取 | 入库 | 复用 | 失败 |
|---|---:|---:|---:|---:|---:|
| gov_procurement | 8 | 6 | 6 | 0 | 0 |
| listed_announcement | 12 | 6 | 6 | 0 | 0 |

- 合计 12 文档 / 12 版本 / 12 索引记录，`index_mismatch = 0`。
- `consistency`: `missing_index = []`，`version_mismatch = []`。
- 临时正文缓存目录 `shared/temp` 为空 → 「处理期缓存、入库即删」生效。
- 巨潮站点列表页为 SPA 模板，改走公告查询 API 取元数据；PDF 正文不在 P0 下载（只存索引与元数据）。

## 3. 单元测试（scripts/run_tests.py，零第三方依赖）

```
7 passed, 0 failed
```

覆盖：URL 规范化、simhash 近似去重、正文抽取与选择器、链接发现、站点注册、同 hash 幂等复用、FTS5/LIKE 检索与域过滤、crawl 任务幂等、一致性检查。

## 4. 固定查询集（eval/queries.json，7 条）

```
total: 7, passed: 7
```

| id | 查询 | 域 | hits | 结果 |
|---|---|---|---:|---|
| q01 | 中标公告 | gov_procurement | 4 | PASS |
| q02 | 采购 | gov_procurement | 6 | PASS |
| q03 | 公告 | listed_announcement | 6 | PASS |
| q04 | 证券 | listed_announcement | 6 | PASS |
| q05 | zzzz-不存在的关键词-xyz | — | 0 | PASS |
| q06 | 成交 | gov_procurement | 2 | PASS |
| q07 | 医院 | gov_procurement | 4 | PASS |

按 V1.1 §18 P0 验收口径：无标注集时不计算 Recall@K/Precision@K，指标为**固定查询集命中数**。

## 5. PoC 暴露并已修正的问题

1. **FTS5 trigram 只索引 ≥3 字符** → 2 字查询（「公告」「采购」）恒为 0。修法：长查询拆 3-gram OR 走 FTS，同时用 LIKE 兜底并合并去重。这正是 V1.1 §3.3 要求 PoC 验证的中文召回问题。
2. **巨潮列表页是 SPA 模板**（`{{item.value}}`），非公告正文 → 新增 `CninfoAdapter.discover_api()` 走公告查询 API。
3. **正文选择器 `div.article` 未命中** → 修正选择器解析支持 `tag.class` / `.class` / `#id` / `tag`。
4. bundled Python 无 pytest / requests / trafilatura / PyYAML → 全程零第三方依赖，域配置用 JSON 代替 YAML（记录为 V1.1 偏差），自测用 `scripts/run_tests.py`。
5. 控制台中文乱码为 PowerShell 输出编码，数据库中文本正常（已直接查库核验）。

## 6. 与 V1.1 的偏差（需知悉）

| 项 | V1.1 | P0 实现 | 原因 |
|---|---|---|---|
| 域配置 | domain.yaml | domain.json | bundled Python 无 PyYAML |
| 正文抽取 | trafilatura | 内置 HTMLParser + 选择器 | 无第三方依赖，P0 验证用 |
| 检索引擎 | P0 FTS5 / P1 Tantivy | P0 FTS5（符合） | — |
| 评估指标 | Recall@K / Precision@K | 固定查询集命中数 | 无标注集，按决断 8 |
| PDF 公告 | 未明确 | 只存 API 元数据，不下载 PDF | P0 不存全文副本 |

## 7. 结论

P0 最小闭环已跑通：定向采集 → 正文/元数据处理 → SQLite 权威存储 → FTS5 检索投影 → CLI 查询 → 固定查询集评测 → 一致性检查 → 临时缓存清理。

未进入 P1（Tantivy）、P2（结构化抽取）、P3（事实验证）。未提交 git、未推送远端。
