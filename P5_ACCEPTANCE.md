# WebSearch Lite P5 验收记录（增量调度、存储迁移与恢复）

时间：2026-11-06
基准：V1.1 §10.4 / §11.4 / §11.5 / §15 / §18 P5，评审决断 ⑥ ⑦

## 1. 实现范围

| 项 | 实现 |
|---|---|
| 增量调度 | `app/scheduler.py`：`due_tasks()` 按 `next_run_at` 判定；`schedule_next()` 成功后按 `update_frequency`（hourly/daily/weekly/monthly）排下次、失败按指数退避（上限 1 天）；`reschedule()` 重新排队保留 ETag |
| 条件请求 | `conditional_fetch()` 带 ETag / If-Modified-Since；304 → 复用当前版本，不重跑抽取/归类/验证 |
| 内容级幂等 | `store.ingest` 同 `content_hash` 复用版本（P0 已实现，P5 验证）；无 ETag 时靠 hash 去重 |
| 崩溃恢复 | `app/recovery.py`：超时 `running`（默认 30 分钟）重置为 `retry_wait`；超过 `max_retries`（默认 3）转 `failed` 并生成 `review_tasks`；`pipeline_tasks` 消费收尾 |
| 存储迁移 | `storage/migration.py`：`schema_migrations` 版本表 + `migrate()` 按序应用、已应用跳过、记录 checksum |
| 备份 | `backup()`：SQLite 在线 backup API + 域配置/Schema/迁移/评估集 + `manifest.json` |
| 恢复 | `verify_backup()` 校验表完整性/文档数/配置；`restore()` 默认 dry-run，`--apply` 才覆盖 |
| 移动盘识别 | `check_storage_paths()`：`storage_path` 不可用时列入 `offline_domains`，不静默返回空 |
| 一致性监测 | `storage/consistency.py`：SQLite vs 检索投影的缺失/版本不匹配/失败任务，`warn` 与 `rebuild_required` 阈值可配（评审决断 ⑦） |
| 索引重建 | `rebuild_index()`：从 SQLite 全量重建 Tantivy + 抽样核验 + 记录 `index_tasks` |
| CLI | `schedule`（`--reschedule`）、`recover`（`--dry-run`）、`migrate`、`backup`、`verify-backup`、`restore`（`--apply`）、`check`、`rebuild`、`storage` |

## 2. 真实库演练

```
schedule --reschedule ccgp   → requeued: 6
schedule --reschedule cninfo → requeued: 6
schedule                     → due: 20, by_status: {pending: 20}

recover → stale_recovered {crawl:0, pipeline:0, index:0}
          retry {requeued:0, failed:0, reviews:0}
          pipeline {consumed: 48}（classify/entity_resolve/verify/index 各 12）

migrate      → applied: [001_init]（幂等，第二次应用为空）
backup       → 10 files，含 registry.db / config / domains / migrations / eval / manifest
verify-backup→ valid: true, documents: 12, missing_tables: []
restore      → dry_run: true, check.valid: true
check        → mismatch: 0, warn: false, engine: fts5
rebuild      → 12 documents rebuilt, 抽样 3/3 验证通过
storage      → offline_domains: []
```

条件请求演练（无 ETag 的历史任务）返回 `modified`，属预期：这批任务首次抓取未存 ETag；后续轮次会带 ETag 并走 304 复用。

## 3. 单元测试

```
41 passed, 0 failed   （P0 7 + P1 6 + P2 8 + P3 7 + P4 6 + P5 7）
```

P5 覆盖：调度到期与重排、304 复用（假 fetcher）、超时 running 恢复、重试耗尽转 failed+复核、pipeline 任务消费、迁移幂等、备份→校验→恢复往返、一致性检查干净。

## 4. 回归

| 项 | 结果 |
|---|---|
| P0 固定查询集 | 7/7 |
| P1 FTS5 / Tantivy | 7/7 / 7/7 |
| P2 eval2 | F1 1.0 |
| P3 eval3 | 15/15 |
| P4 eval4 | Recall@K 1.0、引用正确率 1.0 |
| 索引一致性 | mismatch 0、warn false |
| 存储路径 | offline_domains [] |

## 5. 期间修正

1. `cli schedule --reschedule` 调用了不存在的 `Scheduler.reschedule()` → 补齐实现。
2. `rebuild_index` 记录 `index_tasks` 时用 `"all"` 作为 `domain_id`/`document_id`，触发外键失败 → 改用真实域/文档 id。
3. 备份/校验用 `with sqlite3.connect(...)`（只 commit 不 close）导致 Windows 文件被占用 → 改 `closing()` 显式关闭。

## 6. 偏差与限制

- 增量调度为**单进程手动/定时触发**（`schedule` + cron），未内置常驻调度器；V1.1 §2.1 允许 P0/P1 同进程，P5 仍按需触发。
- `next_run_at` 逻辑存在，但 `crawl` 主流程尚未按它过滤（`due_tasks` 可用，`crawl` 仍取 `pending`）；接常驻调度时切换为 `due_tasks()` 即可。
- 备份不含 Tantivy 索引目录（索引被定义为**可重建投影**，`rebuild` 可从 SQLite 恢复，符合 V1.1 §3.1）。
- `restore --apply` 未做「恢复前自动备份当前库」；生产化前应加。
- 移动盘路径只做存在性检查，未做 I/O 探活/只读检测。
- 断点续跑验证覆盖到任务状态层，未做「进程强杀后重跑」的系统级演练。

## 7. 结论

P5 完成：增量调度、条件请求复用、任务崩溃恢复与有限重试、迁移版本管理、备份/校验/恢复演练、一致性监测与索引重建、存储路径检查均已实现并验收。

P0–P5 全部实施阶段完成。
