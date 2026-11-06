import { useCallback, useEffect, useState } from 'react'
import { api, formatTime } from '../api'
import type { Overview, SearchResponse } from '../types'
import { DomainTag, PredicateTag, StatusTag } from '../components/Tags'
import { DocumentDrawer } from '../components/DocumentDrawer'

const STATUS_FILTERS = [
  { key: '', label: '全部状态' },
  { key: 'verified', label: '已验证' },
  { key: 'single-source', label: '单源' },
  { key: 'conflicting', label: '冲突' },
  { key: 'stale', label: '过期' },
]

const SUGGESTIONS = ['中标公告', '可转换公司债券', '股份回购', '医疗设备采购', '天山电子', '招标公告']

function readUrl(): { q: string; domain: string } {
  const p = new URLSearchParams(window.location.search)
  return { q: p.get('q') ?? '', domain: p.get('domain') ?? '' }
}

export function SearchPage({ overview }: { overview: Overview | null }) {
  const initial = readUrl()
  const [q, setQ] = useState(initial.q)
  const [domain, setDomain] = useState(initial.domain)
  const [status, setStatus] = useState('')
  const [limit, setLimit] = useState(12)
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openDoc, setOpenDoc] = useState<string | null>(null)

  const run = useCallback(
    async (query: string, dom: string, st: string, lim: number) => {
      if (!query.trim()) {
        setData(null)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await api.search(query, dom || undefined, lim, st || undefined)
        setData(res)
        const params = new URLSearchParams()
        params.set('q', query)
        if (dom) params.set('domain', dom)
        window.history.replaceState(null, '', `?${params}`)
      } catch (e) {
        setError((e as Error).message)
        setData(null)
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault()
        document.getElementById('main-search')?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (initial.q) run(initial.q, initial.domain, '', 12)
    // 仅首次挂载时按 URL 恢复
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>定向检索</h1>
          <p>跨政府采购与上市公司公告两域检索，结果绑定 URL 与验证状态</p>
        </div>
        <div className="head-actions">
          <button
            className="btn btn-sm"
            onClick={() => run(q, domain, status, limit)}
            disabled={loading || !q.trim()}
          >
            {loading ? <span className="spinner" /> : null}
            重新检索
          </button>
        </div>
      </div>

      <div className="glass search-hero">
        <div className="search-row">
          <div className="search-input-wrap">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.2-3.2" />
            </svg>
            <input
              id="main-search"
              className="search-input"
              placeholder="搜索公告标题、项目名称、公司或金额…（按 / 聚焦）"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') run(q, domain, status, limit)
              }}
              autoFocus
            />
          </div>
          <button
            className="btn btn-primary"
            style={{ height: 50, padding: '0 22px' }}
            onClick={() => run(q, domain, status, limit)}
            disabled={loading || !q.trim()}
          >
            {loading ? <span className="spinner" /> : null}
            检索
          </button>
        </div>

        <div className="filter-row">
          <button
            className={`chip ${domain === '' ? 'active' : ''}`}
            onClick={() => {
              setDomain('')
              if (q) run(q, '', status, limit)
            }}
          >
            全部域
          </button>
          {(overview?.domains ?? []).map((d) => (
            <button
              key={d.domain_id}
              className={`chip ${domain === d.domain_id ? 'active' : ''}`}
              onClick={() => {
                setDomain(d.domain_id)
                if (q) run(q, d.domain_id, status, limit)
              }}
            >
              {d.label}
              <span className="dim mono" style={{ fontSize: 11 }}>
                {d.documents}
              </span>
            </button>
          ))}
          <span style={{ width: 1, height: 20, background: 'var(--border)' }} />
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.key}
              className={`chip ${status === s.key ? 'active' : ''}`}
              onClick={() => {
                setStatus(s.key)
                if (q) run(q, domain, s.key, limit)
              }}
            >
              {s.label}
            </button>
          ))}
          <select
            className="input"
            style={{ width: 96, height: 30, marginLeft: 'auto' }}
            value={limit}
            onChange={(e) => {
              const v = Number(e.target.value)
              setLimit(v)
              if (q) run(q, domain, status, v)
            }}
          >
            {[8, 12, 20, 30].map((n) => (
              <option key={n} value={n}>
                {n} 条
              </option>
            ))}
          </select>
        </div>
      </div>

      {error ? <div className="banner banner-danger">检索失败：{error}</div> : null}

      {data ? (
        <>
          <div className="metric-grid">
            <div className="metric">
              <div className="metric-label">命中</div>
              <div className="metric-value">{data.results.length}</div>
              <div className="metric-sub">共检索 {data.routed_domains.length} 个域</div>
            </div>
            <div className="metric">
              <div className="metric-label">耗时</div>
              <div className="metric-value">{data.latency_ms}</div>
              <div className="metric-sub">毫秒</div>
            </div>
            <div className="metric">
              <div className="metric-label">引用完整</div>
              <div className="metric-value" style={{ color: data.citations_valid ? 'var(--ok)' : 'var(--danger)' }}>
                {data.citations_valid ? 'OK' : 'FAIL'}
              </div>
              <div className="metric-sub">每条结果带 URL + 版本</div>
            </div>
            <div className="metric">
              <div className="metric-label">路由域</div>
              <div className="metric-value" style={{ fontSize: 15 }}>
                {data.routed_domains.map((d) => (d === 'gov_procurement' ? '采购' : '公告')).join(' / ') || '—'}
              </div>
              <div className="metric-sub">关键词软路由</div>
            </div>
          </div>

          <div className="result-list">
            {data.results.map((r, i) => (
              <article className="result" key={r.doc_id} onClick={() => setOpenDoc(r.doc_id)}>
                <div className="result-title">
                  <span className="result-rank">#{i + 1}</span>
                  <span>{r.title || '（无标题）'}</span>
                </div>
                <div className="result-snippet">{r.snippet || '（无摘要）'}</div>
                <div className="result-meta">
                  <DomainTag domain={r.domain_id} />
                  {[...new Set(r.facts.map((f) => f.verification_status))].map((s) => (
                    <StatusTag key={s} status={s} />
                  ))}
                  {[...new Set(r.facts.map((f) => f.predicate))].slice(0, 4).map((p) => (
                    <PredicateTag key={`p-${p}`} predicate={p} />
                  ))}
                  <span style={{ marginLeft: 'auto' }}>score {r.final_score?.toFixed(3) ?? '—'}</span>
                </div>
                {r.url ? (
                  <div style={{ marginTop: 6 }}>
                    <a
                      className="url"
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {r.url}
                    </a>
                  </div>
                ) : null}
              </article>
            ))}
            {data.results.length === 0 ? (
              <div className="glass empty">
                <div className="empty-badge">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                    <circle cx="11" cy="11" r="7" />
                    <path d="m20 20-3.2-3.2" />
                  </svg>
                </div>
                <div>没有相关结果</div>
                <div style={{ fontSize: 12, maxWidth: 460 }}>
                  本地库里没有与该查询相关的文档。本系统只检索已采集的政府采购与上市公司公告，
                  不是通用搜索引擎，因此「大模型最新知识」这类时效性通用问题不会有结果。
                </div>
                {(data.query_terms?.generic?.length ?? 0) > 0 ? (
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    已被忽略的通用词：
                    {data.query_terms!.generic.map((g) => (
                      <span key={g} className="tag tag-pending" style={{ marginLeft: 6 }}>
                        {g}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <>
          <div className="glass glass-pad">
            <div className="section-label" style={{ marginTop: 0 }}>
              快捷查询
            </div>
            <div className="filter-row">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="chip"
                  onClick={() => {
                    setQ(s)
                    run(s, domain, status, limit)
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="glass glass-pad">
            <div className="section-label" style={{ marginTop: 0 }}>
              最近入库
            </div>
            {(overview?.recent_documents ?? []).length === 0 ? (
              <div className="dim" style={{ fontSize: 12 }}>
                暂无文档，先在「系统」页触发一次采集
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 2 }}>
                {(overview?.recent_documents ?? []).map((d) => (
                  <div
                    key={d.doc_id}
                    onClick={() => setOpenDoc(d.doc_id)}
                    style={{
                      display: 'flex',
                      gap: 12,
                      alignItems: 'center',
                      padding: '10px 8px',
                      borderRadius: 9,
                      cursor: 'pointer',
                      borderBottom: '1px solid rgba(120,150,220,.07)',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,.035)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <DomainTag domain={d.domain_id} />
                    <span
                      style={{
                        flex: 1,
                        minWidth: 0,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        fontSize: 13,
                      }}
                    >
                      {d.title || '（无标题）'}
                    </span>
                    <span className="dim mono" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                      {formatTime(d.fetched_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {openDoc ? <DocumentDrawer docId={openDoc} onClose={() => setOpenDoc(null)} /> : null}
    </>
  )
}
