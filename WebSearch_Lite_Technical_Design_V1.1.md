# WebSearch Lite 技术设计修订版 V1.1

> 个人自用的定向站点搜索系统。面向已登记网站进行持续采集、本地检索、结构化事实沉淀、多源交叉验证与带证据引用的答案生成。
>
> **版本状态：技术设计修订稿，待用户确认后进入实现。**
>
> 本文以 V1.0 为基础，保留原有产品边界和核心架构，补充数据模型、生命周期、任务一致性、质量评估、接口和验收标准。新增内容属于工程修订建议，不代表已实现或已验证。

---

## 0. 修订摘要

### 0.1 保留的核心约束

| 编号 | 约束 |
|---|---|
| C1 | 个人自用独立小系统，不做 DSH 插件、不对外服务 |
| C2 | 不长期保存原始全文副本；长期保存索引、摘要、结构化事实、证据定位及必要的版本元数据 |
| C3 | 不做全网/元搜索。目标站点已知，走站点定向采集与本地索引；元搜索仅可选用于发现新站点 |
| C4 | 一个限定域一个逻辑单元，每域独立索引、配置和归类 Schema，统一汇总层 |
| C5 | 单机运行优先；接口预留未来拆进程/多机能力，不提前引入分布式基础设施 |
| C6 | 每条事实关联 URL、证据段落/文本跨度及抓取时间；模型只在封闭 Schema 内归类、抽取或重排 |
| C7 | 多源交叉验证；权威性按事实类型配置；转载关系识别后再统计独立来源 |
| C8 | 活跃域优先放本机 SSD；归档域或冷备份可放移动盘，路径可配置 |
| C9 | 现有硬件的主要约束预计是遵守站点规则后的采集时长，而非初期索引计算能力 |
| C10 | 先评审设计、再编码；未经确认不继续实现、提交或推送 |

### 0.2 本次修订重点

1. 把“站点已知”与“召回质量已解决”区分开。
2. 明确来源、文档、文档版本、事实、事实版本、证据、转载关系、冲突和复核任务的数据关系。
3. 将 SQLite 定义为元数据与事实的权威存储，Tantivy 定义为可重建的检索投影。
4. 将采集、抽取、索引、归类和验证任务拆分，支持幂等、重试、失败恢复。
5. 明确事实状态不是绝对真理；必须保留证据、来源权威范围、时效与冲突快照。
6. 增加抽取、检索和采集的离线评估方法与 P0 验收指标。
7. 明确模块边界、接口契约和实施阶段。

---

## 1. 目标与边界

### 1.1 目标

对一组预先登记的目标网站做持续定向采集，建立本地索引，提供：

- 统一查询和域路由；
- 关键词检索与结构化过滤；
- 可选的语义检索/重排；
- 结构化事实与证据定位；
- 跨源交叉验证和冲突展示；
- 带 URL、段落/文本跨度、来源和抓取时间的引用答案；
- 站点健康监测、增量更新和故障恢复。

### 1.2 不做

- 全网通用索引、实时网页搜索或搜索引擎替代品；
- 原始 HTML 与全文副本长期留存；
- 对外 API、多租户、SLA、付费搜索 API 依赖；
- 绕过 robots、登录墙、验证码、访问控制或反爬技术措施；
- 初期引入 Kafka、Kubernetes、分布式索引集群；
- 将 `verified` 解释为绝对正确。

### 1.3 核心定位

目标站点已知，解决的是搜索范围和采集入口问题；**召回、抽取、实体匹配、事实验证和时效性仍然需要评估与迭代**。

系统的核心价值在于：

> 持续获取目标站点的信息，能够检索到相关内容，并对结构化事实给出可追溯证据、来源关系、验证状态和时间语义。

---

## 2. 总体架构

```text
                         ┌──────────────────────────────┐
                         │ Query Coordinator            │
                         │ 查询解析 / 域路由 / 合并      │
                         │ 排序 / 证据约束答案生成       │
                         └──────────────┬───────────────┘
                                        │ SearchPort
              ┌─────────────────────────┼────────────────────────┐
              │                         │                        │
       ┌──────▼──────┐           ┌──────▼──────┐          ┌──────▼──────┐
       │ Domain A    │           │ Domain B    │          │ Domain N    │
       │ Index+Facts │           │ Index+Facts │          │ Index+Facts │
       └──────┬──────┘           └──────┬──────┘          └──────┬──────┘
              └─────────────────────────┼────────────────────────┘
                                        │
                 ┌──────────────────────▼──────────────────────┐
                 │ Pipeline / Workers                          │
                 │ Fetch → Extract → Normalize → Dedup         │
                 │ Classify → Entity Resolve → Verify → Index  │
                 └──────────────────────┬──────────────────────┘
                                        │
                 ┌──────────────────────▼──────────────────────┐
                 │ Site Registry + Crawl Frontier              │
                 │ Sitemap / RSS /栏目页 / robots /限速/增量     │
                 └──────────────────────┬──────────────────────┘
                                        │
                 ┌──────────────────────▼──────────────────────┐
                 │ Persistence                                 │
                 │ SQLite：权威元数据、事实、证据、任务、状态   │
                 │ Tantivy：可重建的全文检索投影               │
                 └─────────────────────────────────────────────┘
```

### 2.1 部署形态

- 初期：一个本地应用进程 + SQLite + Tantivy 本地索引目录。
- 任务工作者可以先在同一进程内运行，后续允许拆成独立进程。
- 各域通过 `SearchPort` 统一查询，不依赖其物理部署位置。
- 不因预留扩展而在 MVP 引入 RPC、消息中间件或集群调度。

### 2.2 领域边界

每个 Domain 是一个逻辑单元，包含：

- `domain.yaml`；
- 域级分类 Schema；
- 域级事实模型/字段映射；
- 域级 Tantivy 索引；
- 域级来源配置；
- 域级事实与证据数据。

领域之间不强制互斥。一个来源可以为多个事实类型提供证据，但应由 registry 明确登记其权威范围。

---

## 3. 检索引擎与数据存储

### 3.1 引擎选型

| 组件 | 责任 | 选择 |
|---|---|---|
| 全文索引 | 关键词召回、BM25 排序 | Tantivy（tantivy-py） |
| 结构化事实/元数据 | 文档、版本、事实、证据、任务、冲突 | SQLite |
| PoC/降级检索 | 基础全文搜索 | SQLite FTS5 |
| 语义检索 | 处理词汇差异和语义召回 | 后续按评估结果决定 |
| 模型调用 | 归类、抽取、可选重排/复核 | 本地模型或 API，配置化 |

### 3.2 Tantivy 定位

Tantivy 是本地嵌入式全文检索引擎，不要求云端服务。索引目录可放本机 SSD 或配置的存储路径。

Tantivy 仅作为检索投影，不作为事实的唯一权威存储。索引可从 SQLite 中的文档与索引任务重建。

### 3.3 中文检索

初期采用一种可验证方案：

- jieba 预分词后以空格分隔写入 Tantivy；或
- 字符 2–3 gram。

通过 PoC 对中文短词、企业名称、公告标题、金额/编号等检索样例进行比较后确定。不得仅凭引擎选型推断中文召回质量。

### 3.4 索引字段

建议字段：

```text
doc_id
title
url
canonical_url
domain_id
source_id
published_at
occurred_at（可选）
fetched_at
snippet
entities
fact_refs
content_hash
document_version_id
```

长期索引中不保存完整正文副本。需要引用时优先使用已保存的证据片段；如需回源全文，则重新请求公开 URL，并记录回源时间与结果。

---

## 4. 站点注册与适配器

### 4.1 `domain.yaml` 示例

```yaml
id: gov_procurement
label: 政府采购公告
role: authoritative
authority_scope:
  - procurement_award
  - procurement_notice
trust_weight: 1.0

update_frequency: daily
seed_urls:
  - https://www.example.gov.cn/
sitemap: https://www.example.gov.cn/sitemap.xml

robots_respect: true
rate_limit_rps: 1
max_concurrency: 1

adapter: example_gov_procurement
content_selector: "div.article"
fallback_extractor: trafilatura

classify_schema: procurement_v1
storage_path: "D:/domains/gov_procurement"
```

`trust_weight` 只作为排序或验证规则的配置输入，不应直接等同于事实置信度。

### 4.2 Adapter 接口

```python
from typing import Protocol

class SiteAdapter(Protocol):
    def discover_urls(self) -> list[str]:
        ...

    def extract_metadata(self, html: str, url: str) -> dict:
        ...

    def extract_content(self, html: str, url: str) -> dict:
        ...

    def classify_document_type(self, metadata: dict, text: str) -> str:
        ...
```

### 4.3 通用采集层责任

- robots 规则检查；
- 请求限速和站点级并发；
- 请求超时、重试与退避；
- ETag / Last-Modified；
- Sitemap、RSS、栏目页发现；
- URL frontier；
- 采集状态和健康统计；
- 站点级暂停与恢复。

Adapter 负责站点特有的 HTML、字段、日期、分页与公告类型解析。

### 4.4 站点健康状态

每个来源记录：

```text
source_id
last_success_at
last_failure_at
consecutive_failures
fetch_success_rate
extract_success_rate
last_http_status
last_error_code
```

连续失败达到配置阈值后，暂停该来源的自动重试并标记异常；不能让单个故障来源拖垮整个调度器。

---

## 5. 数据模型

### 5.1 核心实体

```text
Domain
  └── Source
        └── Document
              └── DocumentVersion
                    └── FactEvidence ── FactVersion ── Fact
                                          │
                                          └── FactConflict
                                                  └── ReviewTask

DocumentVersion ── SourceRelationship ── DocumentVersion
```

### 5.2 实体职责

| 实体 | 职责 |
|---|---|
| `domains` | 领域配置与 Schema 版本 |
| `sources` | 站点来源、权威范围、采集策略、健康状态 |
| `documents` | 稳定文档身份、canonical URL、当前版本指针 |
| `document_versions` | 每次内容变化的版本、哈希、元数据和证据文本 |
| `facts` | 稳定事实身份：主体、谓词、领域 |
| `fact_versions` | 值、时间语义、状态、版本化验证结果 |
| `fact_evidences` | 事实版本与文档版本之间的证据关系 |
| `source_relationships` | 原文、转载、联合发布、未知等关系 |
| `fact_conflicts` | 同一事实的分歧快照及裁决状态 |
| `review_tasks` | 需要人工复核的抽取、冲突、来源或规则问题 |
| `crawl_tasks` | URL 发现与采集任务 |
| `pipeline_tasks` | 抽取、归类、验证、索引等可重试任务 |
| `index_tasks` | Tantivy upsert/delete 的待处理任务 |

### 5.3 事实身份与事实版本

事实身份不应把可变值放入主键。

推荐逻辑身份：

```text
fact_key = domain_id + subject_id + predicate + normalized_scope
```

例如采购事实可使用：

```text
主体（采购项目/采购人/供应商）
+ 谓词（中标金额/中标供应商/公告状态）
+ 项目编号或事件范围
```

事实值、发生时间、发布日期、有效时间属于 `fact_versions`。

事件键的生成规则必须按领域定义。不能只用“主体 + 日期 + 类型”作为所有事件的通用键，因为同一主体在同一天可能发生多个同类事件。

### 5.4 时间语义

至少区分：

- `published_at`：来源发布时间；
- `occurred_at`：事件发生时间；
- `valid_from` / `valid_to`：事实有效时间；
- `fetched_at`：本系统抓取时间；
- `verified_at`：系统完成本次验证的时间。

字段可空，并保留原始文本与解析状态，避免模型猜测缺失日期。

### 5.5 证据定位

每条证据应尽可能保存：

```text
document_version_id
url
paragraph_index
char_start
char_end
quoted_text
fetched_at
```

只保留满足引用、复核和审计所需的短证据片段，不保存整篇原始正文副本。证据长度上限和保留策略由配置确定。

---

## 6. SQLite Schema（核心表草案）

> 本节为 V1.1 的逻辑 Schema 草案。正式建表前需结合选定 SQLite 版本、迁移工具和具体领域字段进行一次 SQL 评审。域级扩展字段可放在受版本控制的 JSON 字段中，但关键查询字段应独立列化。

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE domains (
    domain_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    config_path TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL REFERENCES domains(domain_id),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('authoritative','corroborating','reference')),
    authority_scope_json TEXT NOT NULL DEFAULT '[]',
    trust_weight REAL NOT NULL DEFAULT 1.0,
    robots_respect INTEGER NOT NULL DEFAULT 1,
    rate_limit_rps REAL NOT NULL DEFAULT 1.0,
    max_concurrency INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_success_at TEXT,
    last_failure_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_sources_domain ON sources(domain_id);

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL REFERENCES domains(domain_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    current_version_id TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK(lifecycle_status IN ('active','source_deleted','blocked','invalid')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(domain_id, canonical_url)
);

CREATE INDEX idx_documents_source ON documents(source_id);
CREATE INDEX idx_documents_status ON documents(lifecycle_status);

CREATE TABLE document_versions (
    document_version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    version_no INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    extracted_text TEXT,
    published_at TEXT,
    occurred_at TEXT,
    fetched_at TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    http_status INTEGER,
    extraction_status TEXT NOT NULL
        CHECK(extraction_status IN ('success','partial','failed')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(document_id, version_no),
    UNIQUE(document_id, content_hash)
);

CREATE INDEX idx_doc_versions_fetched ON document_versions(fetched_at);
CREATE INDEX idx_doc_versions_published ON document_versions(published_at);

CREATE TABLE facts (
    fact_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL REFERENCES domains(domain_id),
    subject_id TEXT NOT NULL,
    subject_label TEXT,
    predicate TEXT NOT NULL,
    normalized_scope TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(domain_id, subject_id, predicate, normalized_scope)
);

CREATE INDEX idx_facts_subject ON facts(domain_id, subject_id);
CREATE INDEX idx_facts_predicate ON facts(domain_id, predicate);

CREATE TABLE fact_versions (
    fact_version_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES facts(fact_id),
    version_no INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    normalized_value TEXT,
    unit TEXT,
    currency TEXT,
    published_at TEXT,
    occurred_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    verification_status TEXT NOT NULL
        CHECK(verification_status IN
          ('verified','single-source','conflicting','stale','unverified','rejected')),
    verification_summary TEXT,
    verified_at TEXT,
    extractor_model TEXT,
    schema_version TEXT NOT NULL,
    confidence_raw REAL,
    created_at TEXT NOT NULL,
    UNIQUE(fact_id, version_no)
);

CREATE INDEX idx_fact_versions_status ON fact_versions(verification_status);
CREATE INDEX idx_fact_versions_occurred ON fact_versions(occurred_at);

CREATE TABLE fact_evidences (
    evidence_id TEXT PRIMARY KEY,
    fact_version_id TEXT NOT NULL REFERENCES fact_versions(fact_version_id),
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    paragraph_index INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    quoted_text TEXT NOT NULL,
    evidence_role TEXT NOT NULL DEFAULT 'supports'
        CHECK(evidence_role IN ('supports','contradicts','context')),
    evidence_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_evidence_fact_version ON fact_evidences(fact_version_id);
CREATE INDEX idx_evidence_document_version ON fact_evidences(document_version_id);

CREATE TABLE source_relationships (
    relationship_id TEXT PRIMARY KEY,
    from_document_version_id TEXT NOT NULL
        REFERENCES document_versions(document_version_id),
    to_document_version_id TEXT NOT NULL
        REFERENCES document_versions(document_version_id),
    relationship_type TEXT NOT NULL
        CHECK(relationship_type IN ('original','repost','syndicated','references','unknown')),
    confidence REAL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    reviewed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(from_document_version_id, to_document_version_id, relationship_type)
);

CREATE TABLE fact_conflicts (
    conflict_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES facts(fact_id),
    status TEXT NOT NULL
        CHECK(status IN ('open','resolved','dismissed')),
    conflict_snapshot_json TEXT NOT NULL,
    winner_fact_version_id TEXT REFERENCES fact_versions(fact_version_id),
    decision_reason TEXT,
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_conflicts_fact_status ON fact_conflicts(fact_id, status);

CREATE TABLE review_tasks (
    review_task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','in_progress','resolved','dismissed')),
    priority INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    assigned_to TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX idx_review_tasks_status ON review_tasks(status, priority);

CREATE TABLE crawl_tasks (
    crawl_task_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    task_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(task_status IN ('pending','running','succeeded','retry_wait','failed','skipped')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at TEXT,
    etag TEXT,
    last_modified TEXT,
    last_http_status INTEGER,
    last_error TEXT,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, canonical_url)
);

CREATE INDEX idx_crawl_tasks_schedule
    ON crawl_tasks(task_status, next_run_at, priority);

CREATE TABLE pipeline_tasks (
    pipeline_task_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL
        REFERENCES document_versions(document_version_id),
    task_type TEXT NOT NULL
        CHECK(task_type IN ('extract','classify','entity_resolve','verify','index','delete_index')),
    task_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(task_status IN ('pending','running','succeeded','retry_wait','failed','cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_pipeline_schedule
    ON pipeline_tasks(task_status, next_run_at);

CREATE TABLE index_tasks (
    index_task_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL REFERENCES domains(domain_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    document_version_id TEXT REFERENCES document_versions(document_version_id),
    operation TEXT NOT NULL CHECK(operation IN ('upsert','delete')),
    task_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(task_status IN ('pending','running','succeeded','retry_wait','failed')),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_index_tasks_schedule
    ON index_tasks(task_status, next_run_at);

CREATE TABLE query_log (
    query_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    routed_domains_json TEXT NOT NULL DEFAULT '[]',
    result_doc_ids_json TEXT NOT NULL DEFAULT '[]',
    latency_ms INTEGER,
    created_at TEXT NOT NULL
);
```

### 6.1 `extracted_text` 与“不长期保存全文”的边界

上面的 `document_versions.extracted_text` 是可选的处理缓存字段，并非要求长期保存完整正文。正式实现建议默认：

- 处理期间保存在临时缓存；
- 结构化抽取完成后删除全文缓存；
- 长期保留摘要、短证据片段、哈希、字段和定位信息；
- 对用户明确要求归档的域单独设置保留策略。

如果需要严格禁止正文落库，则将 `extracted_text` 移出 SQLite，放临时目录并在任务结束后清理。

---

## 7. 采集与处理 Pipeline

### 7.1 流程

```text
URL Discovery
  → URL Canonicalization
  → Robots / Policy Check
  → Fetch
  → HTTP Metadata Check (ETag / Last-Modified)
  → Extract Main Content
  → Content Hash / Near-Duplicate
  → Document Version
  → Classify (closed schema)
  → Entity Resolve
  → Normalize Values / Time
  → Fact Evidence Creation
  → Fact Verification
  → Index Projection
```

### 7.2 确定性优先

| 功能 | 主要实现 |
|---|---|
| URL 规范化 | 规则代码 |
| robots 与限速 | 规则代码 |
| HTTP 条件请求 | HTTP 客户端 |
| 正文抽取 | Adapter + trafilatura 等抽取库 |
| 内容哈希 | SHA-256 等确定性哈希 |
| 近似重复 | SimHash/相似度 + 可审查阈值 |
| 转载识别 | 相似度、时间、署名、链接关系，必要时模型辅助 |
| Schema 校验 | Pydantic/JSON Schema |
| 金额、单位、日期规范化 | 确定性规则优先 |
| 结构化归类 | LLM |
| 实体消歧 | 规则候选 + 模型辅助 + 人工复核 |
| 事实验证 | 证据、来源权威性、独立性、时间与一致性 |
| 答案生成 | LLM，受证据约束 |

### 7.3 重试与退避

建议配置：

- 网络超时：有限次数重试；
- HTTP 429/5xx：指数退避并遵守 `Retry-After`；
- 4xx 中不可重试错误：记录并跳过；
- robots 禁止：不抓取；
- 连续失败达到阈值：暂停来源并产生健康告警；
- 所有任务使用幂等键，防止重复执行造成重复事实或索引记录。

### 7.4 页面删除或来源不可访问

不能把一次 404、超时或临时错误立即认定为文档永久删除。

建议状态策略：

- 单次失败：保留当前版本，记录失败；
- 连续确认 404/410：标记来源侧删除候选；
- 达到配置的确认条件后：将文档标记 `source_deleted`；
- 原事实版本和证据不物理删除，除非保留策略或用户操作要求删除；
- 检索默认可隐藏来源已删除文档，但历史引用应显示其状态。

---

## 8. 事实验证机制

### 8.1 验证对象

验证对象是结构化事实：

```text
(subject, predicate, normalized_value, time_scope)
```

而不是整篇文档。

### 8.2 验证输入

- 候选事实版本；
- 支持或反驳该事实的证据；
- 来源权威等级及其 `authority_scope`；
- 转载/联合发布关系；
- 证据时间与事实时间；
- 同一事实的历史版本；
- 领域验证规则。

### 8.3 来源独立性

来源计数前先识别转载关系。来源关系可分：

- `original`：原始发布；
- `repost`：转载；
- `syndicated`：联合发布/内容分发；
- `references`：引用但未必转载；
- `unknown`：关系未知。

独立来源数量不应仅由域名数量决定。未知关系不能默认当成独立来源。

### 8.4 权威性与置信度

不采用未经校准的简单公式：

```text
confidence = source_count × trust_weight
```

建议先输出可解释的分量：

```json
{
  "independent_source_count": 2,
  "authority_level": "authoritative",
  "evidence_consistency": "consistent",
  "freshness": "current",
  "extraction_quality": "passed",
  "verification_status": "verified",
  "decision_reason": "..."
}
```

如需计算数值置信度，应基于人工标注集校准，并明确其适用领域。模型自行生成的 confidence 仅作为辅助信号，不直接代表准确率。

### 8.5 状态定义

| 状态 | 含义 |
|---|---|
| `verified` | 当前证据与领域规则满足验证条件；不代表绝对真理 |
| `single-source` | 只有一个可用独立来源，或独立性尚不足 |
| `conflicting` | 存在未解决的实质性证据冲突 |
| `stale` | 事实超过领域配置的时效窗口，或来源显示已过期 |
| `unverified` | 已抽取但尚未完成验证 |
| `rejected` | 证据不支持该事实或抽取被判定错误 |

### 8.6 权威裁决边界

权威源只在其配置的事实类型范围内参与裁决。裁决必须保存：

- 被比较的事实版本；
- 证据快照；
- 裁决理由；
- 裁决规则版本；
- 裁决时间；
- 是否人工确认。

不静默覆盖冲突事实。

### 8.7 人工复核触发条件

- 同一事实的数值、主体或时间冲突；
- 实体匹配置信度低；
- 关键字段缺少证据跨度；
- 证据片段与抽取值无法规则校验；
- 重要权威来源出现更正；
- 自动裁决规则无法给出明确结果。

---

## 9. 实体解析与标准化

### 9.1 实体解析策略

```text
原始名称
  → 清洗与标准化
  → 领域候选生成
  → 唯一标识匹配（如 USCC）
  → 名称/别名/地址等候选评分
  → 规则确定匹配 / 模型辅助
  → 低置信度人工复核
```

### 9.2 企业实体

优先使用统一社会信用代码（USCC）等稳定标识。名称、简称、历史名称、分支机构名称应作为别名或关系，不应简单覆盖主名称。

若没有稳定标识，不得仅凭相似名称自动合并企业实体。

### 9.3 事件实体

事件匹配键由领域定义。应考虑：

- 主体；
- 事件类型；
- 项目编号/公告编号；
- 事件发生时间范围；
- 地域；
- 相关主体。

同一主体同一天发生的多个同类事件不得被错误合并。

---

## 10. 增量更新、任务状态机与恢复

### 10.1 文档生命周期与任务状态分离

文档生命周期：

```text
active
source_deleted
blocked
invalid
```

任务状态：

```text
pending → running → succeeded
              ├→ retry_wait → running
              └→ failed
```

抽取、归类、验证、索引任务分别管理。一个任务失败不应把整个文档的历史版本删除。

### 10.2 Pipeline 状态

```text
DISCOVERED
  → FETCH_PENDING
  → FETCHED
  → EXTRACTED
  → CLASSIFIED
  → VERIFIED / REVIEW_REQUIRED
  → INDEXED
```

状态机是任务执行视图，不代表数据必须单向流动。新版本出现时，可从对应阶段重新执行后续处理。

### 10.3 幂等性

- 文档唯一键：`domain_id + canonical_url`；
- 文档版本唯一键：`document_id + content_hash`；
- Pipeline 任务唯一键：`document_version_id + task_type + schema_version`；
- 索引任务唯一键：文档、版本、操作类型和索引版本组成；
- 重试不得创建重复文档版本或重复事实版本。

### 10.4 崩溃恢复

启动时：

1. 将过期的 `running` 任务恢复为 `retry_wait` 或 `pending`；
2. 检查到期任务；
3. 执行失败任务的有限重试；
4. 对长期失败任务生成复核项；
5. 定期核对 SQLite 文档状态与 Tantivy 索引；
6. 必要时从 SQLite 重建索引。

### 10.5 变更处理

当页面内容哈希变化：

1. 创建新的 `document_version`；
2. 不删除旧版本；
3. 对新版本重新抽取/归类；
4. 创建新事实版本或关联已有事实；
5. 更新验证状态；
6. 创建 Tantivy upsert 任务；
7. 任务成功后更新索引状态。

当页面仅 ETag/Last-Modified 变化但正文哈希未变时，默认不重复进行昂贵的归类和事实验证，可只更新抓取元数据。

---

## 11. SQLite 与 Tantivy 的一致性

### 11.1 原则

- SQLite 是事实和文档状态的权威来源；
- Tantivy 是检索投影；
- 两者不使用跨系统事务；
- 通过 SQLite 任务表实现最终一致性；
- Tantivy 可重建，不作为唯一数据副本。

### 11.2 Upsert 流程

```text
SQLite transaction:
  save document/version/facts/evidence
  insert index_task(idempotency_key, operation='upsert')
COMMIT

Index worker:
  read pending index_task
  build index document from SQLite
  Tantivy upsert + commit
  mark task succeeded
```

### 11.3 Delete 流程

```text
SQLite transaction:
  mark document lifecycle
  insert index_task(operation='delete')
COMMIT

Index worker:
  delete document from Tantivy
  commit
  mark task succeeded
```

删除应采用稳定 `doc_id`，并确保 Tantivy 文档具有可精确删除的字段。

### 11.4 失败与重建

- 索引失败：任务进入 `retry_wait`，不丢失 SQLite 事实；
- 任务重复：通过幂等键避免重复逻辑写入；
- 索引目录损坏：停用当前索引，创建新目录并从 SQLite 重建；
- 重建完成后：切换索引路径/版本，并执行抽样核验；
- 索引提交和 SQLite 任务完成之间若崩溃，重复执行 upsert/delete 应可安全恢复。

### 11.5 一致性监测

周期性检查：

- active 文档是否存在索引记录；
- source_deleted 文档是否仍可被检索；
- 索引中的版本是否对应 SQLite 当前版本；
- 失败任务是否长期积压；
- 索引文档总数与 SQLite 应索引文档数是否存在异常差异。

---

## 12. Query Coordinator

### 12.1 查询流程

```text
User Query
  → Query Parse
  → Domain Routing
  → Query Rewrite (optional)
  → Domain SearchPort.search()
  → Candidate Merge
  → Global Dedup
  → Score Normalization
  → Rerank
  → Fact/Evidence Filtering
  → Answer Generation
  → Citation Validation
```

### 12.2 查询能力

MVP：

- 关键词查询；
- 域过滤；
- 时间过滤；
- 企业/实体过滤；
- 文档类型过滤；
- 事实状态过滤；
- 带来源和证据片段的结果。

后续：

- 同义词扩展；
- 查询改写；
- 语义召回；
- 模型重排；
- 多条件自然语言解析。

### 12.3 跨域排序

不同域的 BM25 分数不可直接比较。建议：

1. 域内按原始分数排序；
2. 转换为域内 rank 或经验证的归一化分数；
3. 结合域权重、来源权威性、时间和证据质量；
4. 进行全局重排；
5. 保留每个结果的原始分数与排序理由用于调试。

初期优先使用 rank-based 合并，避免不同域分数未经校准直接相加。

### 12.4 引用约束

答案中的每个重要事实陈述必须关联至少一条证据：

```json
{
  "claim": "某企业中标金额为……",
  "fact_version_id": "fv_x",
  "evidence_ids": ["ev_a"],
  "verification_status": "verified"
}
```

若事实为 `single-source` 或 `conflicting`，答案必须明确标注，不得写成确定结论。生成后执行引用完整性检查，确保引用 URL、段落、时间可追溯。

---

## 13. 模块接口

### 13.1 SearchPort

```python
from typing import Protocol

class SearchPort(Protocol):
    def search(self, query: str, *, filters: dict | None = None,
               limit: int = 20) -> list[dict]:
        ...

    def upsert(self, doc_id: str, document: dict) -> None:
        ...

    def delete(self, doc_id: str) -> None:
        ...

    def stats(self) -> dict:
        ...
```

### 13.2 Fetcher

```python
class FetchResult:
    url: str
    status_code: int | None
    headers: dict
    body: bytes | None
    fetched_at: str
    error: str | None

class Fetcher(Protocol):
    def fetch(self, url: str, *, etag: str | None = None,
              last_modified: str | None = None) -> FetchResult:
        ...
```

### 13.3 Extractor

```python
class Extractor(Protocol):
    def extract(self, html: bytes, url: str) -> dict:
        # title, text, paragraphs, published_at_raw,
        # canonical_url, metadata, extraction_status
        ...
```

### 13.4 Classifier

```python
class Classifier(Protocol):
    def classify(self, text: str, schema: dict,
                 evidence_context: dict | None = None) -> dict:
        # 输出必须符合领域封闭 Schema。
        # 可用的关键字段应尽量包含 source span/evidence。
        ...
```

### 13.5 Verifier

```python
class Verifier(Protocol):
    def verify(self, fact_version_id: str) -> dict:
        # 返回验证状态、证据集合、独立来源分析、
        # 决策理由与是否需要人工复核。
        ...
```

### 13.6 统一错误模型

建议错误至少包括：

```text
NETWORK_TIMEOUT
ROBOTS_DISALLOWED
HTTP_RETRYABLE
HTTP_PERMANENT
EXTRACTION_FAILED
SCHEMA_VALIDATION_FAILED
ENTITY_AMBIGUOUS
EVIDENCE_MISSING
INDEX_WRITE_FAILED
SOURCE_HEALTH_DEGRADED
```

错误码用于调度、监测和复核，不以自由文本作为唯一判断条件。

---

## 14. 质量评估与可观测性

### 14.1 采集质量

每个来源统计：

- URL 发现数；
- 请求成功率；
- 正文抽取可用率；
- 页面类型分布；
- 重复率；
- 最近成功时间；
- 连续失败数；
- 变更检测命中率。

### 14.2 检索质量

建立固定查询集，至少覆盖：

- 精确标题；
- 企业名称/简称；
- 公告编号；
- 同义词；
- 自然语言查询；
- 时间与地域过滤；
- 无结果查询。

指标：

- Recall@K；
- Precision@K；
- MRR 或 nDCG@K；
- 引用正确率；
- 查询延迟。

### 14.3 抽取质量

按领域人工标注样本，计算字段级：

- Precision；
- Recall；
- F1；
- 金额/单位准确率；
- 日期字段准确率；
- 主体实体匹配准确率；
- 证据跨度有效率。

模型的自报 confidence 不作为准确率。需要数值置信度时，使用人工标注集进行校准。

### 14.4 验证质量

抽查：

- 转载关系识别的误判率；
- 独立来源识别准确率；
- 权威源裁决错误率；
- 冲突漏检率；
- stale 状态误判率；
- 人工复核任务的处理结果。

### 14.5 评估数据集

P0 从每个初始领域建立至少 30–50 条小型人工核验样本，用于启动迭代；P2/P3 扩展到每个领域约 100 条或更多，覆盖边界和冲突样本。

样本量是初期工程建议，不是统计学保证。评估集应固定版本，避免模型/规则变更后只使用新样本造成结果不可比。

---

## 15. 存储布局与备份

```text
websearch-lite/
├── src/
│   ├── app/
│   ├── crawler/
│   │   ├── core/
│   │   └── adapters/
│   ├── pipeline/
│   ├── indexing/
│   ├── facts/
│   ├── verification/
│   ├── query/
│   ├── storage/
│   └── evaluation/
├── domains/
│   └── <domain_id>/
│       ├── domain.yaml
│       ├── schema/
│       ├── index/
│       └── facts.db
├── shared/
│   ├── registry.db
│   ├── crawl_queue.db
│   ├── query_log.db
│   └── temp/
├── migrations/
├── tests/
├── config.yaml
└── README.md
```

### 15.1 移动盘策略

- 活跃域默认本机 SSD；
- 归档域或冷备份可移动盘；
- 移动盘上的 SQLite 使用谨慎的写入策略，避免热拔；
- 定期备份 SQLite；
- Tantivy 索引可重建，但备份可缩短恢复时间；
- registry 记录路径和最后可用时间；
- 归档域不可用时，查询应明确提示，而不是静默返回空结果。

### 15.2 备份原则

至少备份：

- SQLite 数据库；
- 域配置和 Schema；
- 迁移记录；
- 必要的索引快照（可选）；
- 评估数据集。

备份恢复必须通过实际演练验证。

---

## 16. 合规与数据保留

- 遵守 robots 与网站条款；
- 低速率、站点级串行优先；
- 不绕登录墙、验证码或技术访问限制；
- 不采集不必要的个人信息；
- 不对外提供服务；
- 不长期保留原始全文副本；
- 对每个来源记录采集依据、策略和数据保留配置；
- 站点授权或政策变化时可暂停、删除或调整该来源数据。

个人自用并不自动意味着所有抓取与存储行为均合规；应逐站确认适用条款与法律要求。

---

## 17. 容量与性能估算

V1.0 的粗略估算可作为初期规划：

| 文档量 | 抽取正文按约 5 KB/页 | 正文与索引粗略合计 |
|---:|---:|---:|
| 10 万 | 约 500 MB | 约 1 GB |
| 100 万 | 约 5 GB | 约 10 GB |
| 1000 万 | 约 50 GB | 约 100 GB |

此估算不包含所有数据库版本、临时文件、备份、索引合并空间和证据保留开销。实际容量应使用首批数据测量后更新。

采集时间的粗略估算：

```text
10,000 URLs @ 1 request/sec ≈ 2.8 小时（仅理论请求时间）
1,000,000 URLs @ 1 request/sec ≈ 11.6 天（仅理论请求时间）
```

实际运行会受到 robots、响应延迟、失败重试、页面解析和站点限速影响。

---

## 18. 实施计划与验收标准

### P0：定向采集与基础检索 PoC

实现：

- 2–3 个公开且结构稳定的网站；
- Sitemap/RSS/栏目页发现；
- robots、限速、重试；
- Adapter；
- 正文抽取；
- canonical URL 与内容哈希；
- SQLite 元数据；
- SQLite FTS5 检索；
- CLI 查询与 URL 引用。

建议验收：

| 指标 | 初期目标 |
|---|---:|
| 合法可访问页面采集成功率 | ≥ 95%（排除站点主动限制等已分类情况） |
| 正文抽取可用率 | ≥ 90%（人工抽样定义“可用”） |
| 文档 URL 去重 | 固定测试样本无重复逻辑记录 |
| 引用完整性 | 每条搜索结果具有 URL 与抓取时间 |
| 恢复能力 | 中断后可继续，不重复创建文档版本 |
| 检索 | 固定查询集可评估 Recall@K/Precision@K |

### P1：Tantivy 检索

实现：

- `SearchPort`；
- Tantivy 本地索引；
- 中文分词 PoC；
- upsert/delete；
- 索引重建；
- SQLite FTS5 对照测试。

验收：

- 中文固定查询集与 FTS5 比较；
- 检索结果能回溯文档版本；
- 索引损坏后可重建；
- 不同域索引分离有效。

### P2：结构化抽取与实体解析

实现：

- 封闭 Schema；
- 模型结构化输出；
- 字段规范化；
- 证据跨度；
- 实体解析；
- 日期/金额口径；
- 人工标注集。

验收：

- 关键字段级 Precision/Recall/F1；
- 金额单位和时间错误可被测试集发现；
- 缺证据的关键字段进入复核；
- 低置信度实体不自动合并。

### P3：事实验证

实现：

- 事实键；
- 事实版本；
- 证据关系；
- 转载识别；
- 来源独立性；
- 权威范围；
- 冲突快照；
- 复核队列。

验收：

- 测试集中转载不被重复计为独立源；
- 冲突不静默覆盖；
- 权威裁决保留理由和证据快照；
- `verified`、`single-source`、`conflicting`、`stale` 状态行为可测试。

### P4：统一查询与引用答案

实现：

- 域路由；
- 结构化过滤；
- 跨域 rank 合并；
- 全局去重；
- 重排；
- 证据约束答案；
- 引用完整性检查。

验收：

- 固定查询集评估 Recall@K、nDCG@K；
- 跨域分数不直接混用未经校准的 BM25 原始分数；
- 每个重要答案陈述可定位证据；
- 冲突和单源事实有明确标记。

### P5：增量调度、存储迁移和恢复

实现：

- 周期调度；
- ETag/Last-Modified；
- 变更检测；
- 任务恢复；
- SQLite/Tantivy 一致性检查；
- 移动盘路径；
- 备份恢复演练；
- 来源健康状态。

验收：

- 进程中断后任务可恢复；
- 同一内容重复抓取不会重复生成版本；
- Tantivy 可从 SQLite 重建；
- 移动盘离线时系统能识别并提示；
- 备份能够实际恢复。

---

## 19. 未决事项

进入 P0 前需要确认：

1. 第一批 2–3 个站点具体是哪几个？
2. 站点是否公开、是否有 Sitemap/RSS、是否允许计划频率？
3. P0 采用 SQLite FTS5，P1 再接 Tantivy，是否确认？
4. 归类模型使用本地模型还是现有 API？
5. CLI 起步还是同步开发最小 Web UI？
6. 是否允许短期缓存正文？若不允许，证据段落如何在抽取时持久化？
7. 首批领域的事实 Schema 与人工评估样本由谁确认？

---

## 20. 修订结论

V1.1 保留 WebSearch Lite 的总体方向：

- 定向采集，不做全网搜索；
- 单机优先；
- 每域独立索引与 Schema；
- SQLite 保存事实与证据；
- Tantivy 作为本地全文检索投影；
- 确定性逻辑优先，模型负责语义任务；
- 交叉验证先识别转载；
- 冲突保留，不静默覆盖；
- 索引可重建；
- 先以 P0 数据质量验证项目价值。

当前不建议推翻总体架构，也不建议直接进入全量编码。应先确认首批网站与 P0 验收样本，再实现最小闭环。

**V1.1 的目标是让关键设计原则转化为可测试、可恢复、可追溯的工程机制。**
