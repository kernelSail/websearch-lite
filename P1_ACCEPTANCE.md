# WebSearch Lite P1 验收记录（Tantivy 检索）

时间：2026-11-05
环境：Python 3.12.14 / tantivy 0.27.0（Rust 内嵌）/ jieba / SQLite 3.53.1 (FTS5 对照)

## 1. 实现范围（V1.1 §18 P1）

| 项 | 实现 |
|---|---|
| `SearchPort` | `indexing/port.py`，接口 `search/upsert/delete/stats/rebuild` |
| FTS5 适配器 | `indexing/fts5_port.py`，作为 P0 对照基线 |
| Tantivy 投影 | `indexing/tantivy_port.py`，每域一个索引目录、`Index.open` 持久化、writer commit + reload |
| 中文分词 | jieba 预分词空格写入；缺失时字符 3-gram 兜底 |
| 查询 | 分词后显式 `OR` 拼接（默认 AND 会让中文多词互相抵消） |
| 中文查询修复 | `parse_query` 多词需 OR；`searcher.doc()` 用 `to_dict()` 取值 |
| 索引重建 | `rebuild()` 从 `documents_index`（SQLite 权威）全量重建，释放 writer 后删目录再建 |
| 域分离 | 每域独立索引目录，查询可指定 `domain_id` 过滤 |
| 跨域排序 | 域内 BM25 原始分 → `rank_normalized`，不直接比较不同域原始分（V1.1 §12.3） |
| 可插拔 | `build_search_port(config)` 按 `search_engine` 切换，上层不改 |
| 对照评测 | `eval/p1_compare.py` + `scripts/p1_index.py compare` |

## 2. 索引重建

```
python scripts/p1_index.py rebuild
→ gov_procurement: 6 docs, listed_announcement: 6 docs, total: 12
→ 重新实例化 TantivySearchPort 后仍为 6/6（持久化验证通过）
```

## 3. 固定查询集对照（eval/queries.json，7 条）

| 引擎 | 通过 | 平均延迟 | 各查询命中数 |
|---|---:|---:|---|
| SQLite FTS5 | **7/7** | 4.43 ms | [4, 6, 6, 6, 0, 2, 4] |
| Tantivy | **7/7** | 3.00 ms | [6, 6, 6, 6, 0, 2, 4] |

Tantivy 在 q01「中标公告」召回更全（6 vs 4），其余一致；无结果查询（q05）两引擎均 0。

## 4. 单元测试（`scripts/run_tests.py`）

```
13 passed, 0 failed   （P0 7 + P1 6）
```

P1 覆盖：中文分词、rebuild 与检索、upsert/delete、域分离、重复 rebuild 覆盖旧数据、Index.open 持久化重载。

## 5. PoC 期间暴露并修正的问题

1. **项目根路径硬编码错误**：`parents[2/3]` 在不同深度文件指向错误目录 → 新增 `paths.find_project_root()` 按 `config.json + migrations/` 向上查找，全项目统一。
2. **Tantivy 中文查询全 0**：jieba 分词后用 `parse_query` 默认 AND，多词互相抵消 → 改显式 `OR` 拼接。
3. **重建后索引目录为空**：`self.domains` 持有的 writer/index 未释放导致 Windows 目录删除失败，且删根目录后未重建 → rebuild 先释放 writer、删子目录后 `root.mkdir()` 重建。
4. **`Index(schema, path)` 重载已存在索引失败** → 改 `tantivy.Index.open(path)`。
5. **`searcher.doc()` 字段读取报错** → 改 `doc.to_dict()`。
6. 残留误建目录（`D:\study\domains_index` 等）已清理。

## 6. 偏差与限制

- Tantivy 通过 pip 安装到 bundled Python（`tantivy 0.27.0` + `jieba`），不再是「零第三方依赖」；P0 的 FTS5 路径仍零依赖可用。
- `documents_index` 仍由 P0 `store.ingest` 同步维护；P1 未改写入链路，`index_tasks` 尚未由独立 worker 消费（P5 范围）。
- 未实现语义检索与模型重排（V1.1 §3.1 后续项）。
- PDF 公告仍只存 API 元数据，不下载正文（P0 偏差延续）。

## 7. 结论

P1 完成：Tantivy 作为可重建的检索投影已接入，中文召回经 PoC 修正后通过固定查询集，域分离与重建/持久化可用，`SearchPort` 抽象保证上层不改。

下一步为 P2（结构化抽取与实体解析），未获指示不继续。
