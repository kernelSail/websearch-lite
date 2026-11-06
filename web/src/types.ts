export type VerificationStatus =
  | 'verified'
  | 'single-source'
  | 'conflicting'
  | 'stale'
  | 'unverified'
  | 'rejected'

export interface FactRef {
  predicate: string
  normalized_value: string
  verification_status: VerificationStatus
  fact_version_id: string
  subject: string
}

export interface SearchResult {
  doc_id: string
  document_version_id: string | null
  title: string | null
  url: string | null
  snippet: string | null
  domain_id: string
  fetched_at: string | null
  final_score: number | null
  term_coverage: number | null
  phrase_hit: number | null
  facts: FactRef[]
}

export interface SearchResponse {
  query: string
  answer: string
  citations_valid: boolean
  routed_domains: string[]
  latency_ms: number
  results: SearchResult[]
  query_terms?: {
    specific: string[]
    generic: string[]
    df: Record<string, number>
  }
}

export interface Overview {
  stats: Record<string, number>
  verification: Record<string, number>
  domains: Array<{
    domain_id: string
    label: string
    enabled: number
    documents: number
    facts: number
  }>
  sources: Array<{
    source_id: string
    name: string
    last_success_at: string | null
    last_failure_at: string | null
    consecutive_failures: number
    enabled: number
  }>
  consistency: {
    missing_index: string[]
    version_mismatch: string[]
  }
  recent_documents: Array<{
    doc_id: string
    title: string | null
    domain_id: string
    canonical_url: string | null
    fetched_at: string | null
  }>
  recent_runs: Array<{
    run_id: string
    code_version: string | null
    schema_version: string | null
    started_at: string
    finished_at: string | null
  }>
  engine: string
  classifier: string
}

export interface DocumentRow {
  doc_id: string
  document_id: string
  document_version_id: string
  title: string | null
  canonical_url: string | null
  snippet: string | null
  domain_id: string
  source_id: string | null
  fetched_at: string | null
  published_at: string | null
  content_hash: string | null
}

export interface DocumentDetail {
  found: boolean
  document?: DocumentRow
  versions?: Array<{
    document_version_id: string
    title: string | null
    published_at: string | null
    fetched_at: string | null
    content_hash: string | null
    extraction_status: string | null
  }>
  evidences?: Array<{
    evidence_id: string
    quoted_text: string
    char_start: number
    char_end: number
    evidence_role: string
    predicate: string
    normalized_value: string
    verification_status: VerificationStatus
    fact_version_id: string
    subject: string
  }>
}

export interface FactRow {
  fact_id: string
  domain_id: string
  predicate: string
  subject: string
  fact_version_id: string
  normalized_value: string
  unit: string | null
  currency: string | null
  verification_status: VerificationStatus
  verification_summary: string | null
  schema_version: string
  extractor_model: string | null
  created_at: string
  evidence_count: number
}

export interface ConflictRow {
  conflict_id: string
  fact_id: string
  status: string
  conflict_snapshot_json: string
  winner_fact_version_id: string | null
  decision_reason: string | null
  decided_by: string | null
  decided_at: string | null
  created_at: string
  updated_at: string
}

export interface ReviewRow {
  review_task_id: string
  task_type: string
  target_type: string
  target_id: string
  status: string
  priority: number
  reason: string
  payload_json: string
  created_at: string
}
