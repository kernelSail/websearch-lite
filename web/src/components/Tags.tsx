import type { VerificationStatus } from './types'

const LABELS: Record<string, string> = {
  verified: '已验证',
  'single-source': '单源',
  conflicting: '冲突',
  stale: '过期',
  unverified: '未验证',
  rejected: '已否决',
}

const CLASSES: Record<string, string> = {
  verified: 'tag-verified',
  'single-source': 'tag-single',
  conflicting: 'tag-conflict',
  stale: 'tag-stale',
  unverified: 'tag-pending',
  rejected: 'tag-conflict',
}

export function statusLabel(status: string): string {
  return LABELS[status] ?? status
}

export function StatusTag({ status }: { status: VerificationStatus | string }) {
  return <span className={`tag ${CLASSES[status] ?? 'tag-pending'}`}>{statusLabel(status)}</span>
}

export function DomainTag({ domain }: { domain: string }) {
  const text = domain === 'gov_procurement' ? '政府采购' : domain === 'listed_announcement' ? '上市公司公告' : domain
  return <span className="tag tag-domain">{text}</span>
}

export function PredicateTag({ predicate }: { predicate: string }) {
  return <span className="tag tag-fact">{predicate}</span>
}
