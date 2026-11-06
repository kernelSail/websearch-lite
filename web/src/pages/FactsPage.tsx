import { useEffect, useMemo, useState } from 'react'
import { api, formatTime } from '../api'
import type { FactRow, Overview } from '../types'
import { DomainTag, PredicateTag, StatusTag } from '../components/Tags'

export function FactsPage({ overview }: { overview: Overview | null }) {
  const [facts, setFacts] = useState<FactRow[]>([])
  const [domain, setDomain] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<'created' | 'predicate'>('created')

  useEffect(() => {
    let alive = true
    setLoading(true)
    api
      .facts(domain || undefined, status || undefined, 300)
      .then((d) => alive && setFacts(d.facts))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [domain, status])

  const sorted = useMemo(() => {
    const list = [...facts]
    if (sortKey === 'predicate') {
      list.sort((a, b) => a.predicate.localeCompare(b.predicate) || a.subject.localeCompare(b.subject))
    }
    return list
  }, [facts, sortKey])

  const grouped = useMemo(() => {
    const map = new Map<string, number>()
    for (const f of facts) map.set(f.predicate, (map.get(f.predicate) ?? 0) + 1)
    return [...map.entries()].sort((a, b) => b[1] - a[1])
  }, [facts])

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>结构化事实</h1>
          <p>每条事实都有版本、证据数与验证状态；金额/日期已规范化</p>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">事实版本</div>
          <div className="metric-value">{facts.length}</div>
          <div className="metric-sub">当前筛选下</div>
        </div>
        <div className="metric">
          <div className="metric-label">已验证</div>
          <div className="metric-value" style={{ color: 'var(--ok)' }}>
            {facts.filter((f) => f.verification_status === 'verified').length}
          </div>
          <div className="metric-sub">多独立源 / 权威裁决</div>
        </div>
        <div className="metric">
          <div className="metric-label">单源</div>
          <div className="metric-value" style={{ color: 'var(--warn)' }}>
            {facts.filter((f) => f.verification_status === 'single-source').length}
          </div>
          <div className="metric-sub">待第二来源佐证</div>
        </div>
        <div className="metric">
          <div className="metric-label">冲突 / 未验证</div>
          <div className="metric-value" style={{ color: 'var(--danger)' }}>
            {facts.filter((f) => f.verification_status === 'conflicting' || f.verification_status === 'unverified').length}
          </div>
          <div className="metric-sub">需人工或裁决</div>
        </div>
      </div>

      <div className="glass glass-pad">
        <div className="filter-row">
          <button className={`chip ${domain === '' ? 'active' : ''}`} onClick={() => setDomain('')}>
            全部域
          </button>
          {(overview?.domains ?? []).map((d) => (
            <button
              key={d.domain_id}
              className={`chip ${domain === d.domain_id ? 'active' : ''}`}
              onClick={() => setDomain(d.domain_id)}
            >
              {d.label}
            </button>
          ))}
          <span style={{ width: 1, height: 20, background: 'var(--border)' }} />
          {['', 'verified', 'single-source', 'conflicting', 'unverified'].map((s) => (
            <button
              key={s || 'all'}
              className={`chip ${status === s ? 'active' : ''}`}
              onClick={() => setStatus(s)}
            >
              {s === '' ? '全部状态' : s === 'verified' ? '已验证' : s === 'single-source' ? '单源' : s === 'conflicting' ? '冲突' : '未验证'}
            </button>
          ))}
          <button
            className={`chip ${sortKey === 'predicate' ? 'active' : ''}`}
            style={{ marginLeft: 'auto' }}
            onClick={() => setSortKey(sortKey === 'created' ? 'predicate' : 'created')}
          >
            排序：{sortKey === 'created' ? '最新' : '谓词'}
          </button>
        </div>
        {grouped.length ? (
          <div className="result-meta" style={{ marginTop: 12 }}>
            {grouped.map(([p, n]) => (
              <span key={p} className="tag tag-fact">
                {p} · {n}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {error ? <div className="banner banner-danger">{error}</div> : null}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>主体</th>
              <th>谓词</th>
              <th>值</th>
              <th>状态</th>
              <th>证据</th>
              <th>分类器</th>
              <th>域</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={8}>
                      <div className="skeleton" style={{ height: 14 }} />
                    </td>
                  </tr>
                ))
              : sorted.map((f) => (
                  <tr key={f.fact_version_id}>
                    <td style={{ maxWidth: 260, wordBreak: 'break-word' }}>{f.subject}</td>
                    <td>
                      <PredicateTag predicate={f.predicate} />
                    </td>
                    <td className="mono" style={{ color: '#cfe8ff' }}>
                      {f.normalized_value}
                      {f.unit ? <span className="dim"> {f.unit}</span> : null}
                    </td>
                    <td>
                      <StatusTag status={f.verification_status} />
                    </td>
                    <td className="mono dim">{f.evidence_count}</td>
                    <td className="mono dim" style={{ fontSize: 11 }}>
                      {f.extractor_model ?? '—'}
                    </td>
                    <td>
                      <DomainTag domain={f.domain_id} />
                    </td>
                    <td className="dim" style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                      {formatTime(f.created_at)}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
        {!loading && sorted.length === 0 ? (
          <div className="empty">该筛选条件下没有事实</div>
        ) : null}
      </div>
    </>
  )
}
