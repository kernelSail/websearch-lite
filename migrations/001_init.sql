PRAGMA foreign_keys = ON;

-- 域与来源
CREATE TABLE IF NOT EXISTS domains (
  domain_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  config_path TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
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
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain_id);

-- 实体（评审补齐 ①）
CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL REFERENCES domains(domain_id),
  canonical_entity_id TEXT,
  uscc TEXT,
  primary_name TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT 'unknown',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain_id, primary_name);
CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  alias TEXT NOT NULL,
  alias_type TEXT NOT NULL DEFAULT 'name',
  source TEXT,
  confidence REAL,
  created_at TEXT NOT NULL,
  UNIQUE(entity_id, alias)
);

-- 文档与版本（评审补齐 ⑥：同 hash 复用，不建新版本）
CREATE TABLE IF NOT EXISTS documents (
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
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);

CREATE TABLE IF NOT EXISTS document_versions (
  document_version_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(document_id),
  version_no INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  title TEXT,
  snippet TEXT,
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
CREATE INDEX IF NOT EXISTS idx_doc_versions_fetched ON document_versions(fetched_at);

-- 事实链路
CREATE TABLE IF NOT EXISTS facts (
  fact_id TEXT PRIMARY KEY,
  domain_id TEXT NOT NULL REFERENCES domains(domain_id),
  subject_id TEXT NOT NULL REFERENCES entities(entity_id),
  predicate TEXT NOT NULL,
  normalized_scope TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(domain_id, subject_id, predicate, normalized_scope)
);

CREATE TABLE IF NOT EXISTS fact_versions (
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
  verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK(verification_status IN ('verified','single-source','conflicting','stale','unverified','rejected')),
  verification_summary TEXT,
  verified_at TEXT,
  extractor_model TEXT,
  schema_version TEXT NOT NULL,
  confidence_raw REAL,
  run_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(fact_id, version_no)
);

CREATE TABLE IF NOT EXISTS fact_evidences (
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

-- 转载关系（评审补齐 ②：from=原文, to=派生）
CREATE TABLE IF NOT EXISTS source_relationships (
  relationship_id TEXT PRIMARY KEY,
  from_document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
  to_document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
  relationship_type TEXT NOT NULL
    CHECK(relationship_type IN ('original','repost','syndicated','references','unknown')),
  confidence REAL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  reviewed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(from_document_version_id, to_document_version_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS fact_conflicts (
  conflict_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL REFERENCES facts(fact_id),
  status TEXT NOT NULL CHECK(status IN ('open','resolved','dismissed')),
  conflict_snapshot_json TEXT NOT NULL,
  winner_fact_version_id TEXT REFERENCES fact_versions(fact_version_id),
  decision_reason TEXT,
  decided_by TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_tasks (
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

-- 原始候选（评审补齐 ③）
CREATE TABLE IF NOT EXISTS raw_fact_candidates (
  candidate_id TEXT PRIMARY KEY,
  document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
  run_id TEXT,
  raw_json TEXT NOT NULL,
  schema_version TEXT,
  validation_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(validation_status IN ('pending','accepted','rejected')),
  reject_reason TEXT,
  created_at TEXT NOT NULL
);

-- 处理运行（评审补齐 ④）
CREATE TABLE IF NOT EXISTS processing_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  git_sha TEXT,
  code_version TEXT,
  model_name TEXT,
  model_endpoint TEXT,
  prompt_version TEXT,
  rule_version TEXT,
  schema_version TEXT,
  config_hash TEXT
);

-- 任务表
CREATE TABLE IF NOT EXISTS crawl_tasks (
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
CREATE INDEX IF NOT EXISTS idx_crawl_schedule ON crawl_tasks(task_status, next_run_at, priority);

CREATE TABLE IF NOT EXISTS pipeline_tasks (
  pipeline_task_id TEXT PRIMARY KEY,
  document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id),
  task_type TEXT NOT NULL
    CHECK(task_type IN ('extract','classify','entity_resolve','verify','index','delete_index')),
  task_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(task_status IN ('pending','running','succeeded','retry_wait','failed','cancelled')),
  idempotency_key TEXT NOT NULL UNIQUE,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_run_at TEXT,
  error_code TEXT,
  error_message TEXT,
  run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_tasks (
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

CREATE TABLE IF NOT EXISTS query_log (
  query_id TEXT PRIMARY KEY,
  query_text TEXT NOT NULL,
  routed_domains_json TEXT NOT NULL DEFAULT '[]',
  result_doc_ids_json TEXT NOT NULL DEFAULT '[]',
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);

-- 检索投影（P0 用 FTS5，对应 V1.1 §3.1 降级方案）
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
  title, snippet, entities,
  content='documents_index', content_rowid='rowid', tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS documents_index (
  doc_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  title TEXT,
  snippet TEXT,
  entities TEXT,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  document_version_id TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS documents_index_ai AFTER INSERT ON documents_index BEGIN
  INSERT INTO documents_fts(rowid, title, snippet, entities)
  VALUES (new.rowid, new.title, new.snippet, new.entities);
END;
CREATE TRIGGER IF NOT EXISTS documents_index_ad AFTER DELETE ON documents_index BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, snippet, entities)
  VALUES ('delete', old.rowid, old.title, old.snippet, old.entities);
END;
CREATE TRIGGER IF NOT EXISTS documents_index_au AFTER UPDATE ON documents_index BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, snippet, entities)
  VALUES ('delete', old.rowid, old.title, old.snippet, old.entities);
  INSERT INTO documents_fts(rowid, title, snippet, entities)
  VALUES (new.rowid, new.title, new.snippet, new.entities);
END;
