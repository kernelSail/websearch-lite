import { useCallback, useEffect, useState } from 'react'
import { api, formatTime } from '../api'
import type { Overview, SearchResponse, WebSearchResponse } from '../types'
import { DomainTag, PredicateTag, StatusTag } from '../components/Tags'
import { DocumentDrawer } from '../components/DocumentDrawer'
import { useToast } from '../components/Toast'

const STATUS_FILTERS = [
  { key: '', label: '全部状态' },
  { key: 'verified', label: '已验证' },
  { key: 'single-source', label: '单源' },
  { key: 'conflicting', label: '冲突' },
  { key: 'stale', label: '过期' },
]

const SUGGESTIONS = ['中标公告', '可转换公司债券', '股份回购', '医疗设备采购', '天山电子', '招标公告']

function readUrl(): { q: string; domain: string; mode: 'local' | 'web' } {
  const p = new URLSearchParams(window.location.search)
  return {
    q: p.get('q') ?? '',
    domain: p.get('domain') ?? '',
    mode: p.get('mode') === 'web' ? 'web' : 'local',
  }
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
  // 联网模式：本地库没有的内容现场去搜
  const [mode, setMode] = useState<'local' | 'web'>(initial.mode)
  const [web, setWeb] = useState<WebSearchResponse | null>(null)
  const [webLoading, setWebLoading] = useState(false)
  const [ingesting, setIngesting] = useState<string | null>(null)
  const [ingested, setIngested] = useState<Record<string, string>>({})
  const toast = useToast()

  const runWeb = useCallback(async (query: string) => {
    if (!query.trim()) {
      setWeb(null)
      return
    }
    setWebLoading(true)
    setError(null)
    try {
      const res = await api.websearch(query, 10)
      setWeb(res)
      const params = new URLSearchParams()
      params.set('q', query)
      params.set('mode', 'web')
      window.history.replaceState(null, '', `?${params}`)
    } catch (e) {
      setError((e as Error).message)
      setWeb(null)
    } finally {
      setWebLoading(false)
    }
  }, [])

  const doIngest = async (url: string) => {
    setIngesting(url)
    try {
      const res = await api.ingest(url)
      if (res.ok) {
        toast.push('ok', `已收录：${(res.title ?? url).slice(0, 40)}`)
        setIngested((prev) => ({ ...prev, [url]: res.document_id ?? 'ok' }))
      } else {
        toast.push('err', res.error ?? '收录失败')
      }
    } catch (e) {
      toast.push('err', (e as Error).message)
    } finally {
      setIngesting(null)
    }
  }

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

  const submit = useCallback(() => {
    if (mode === 'web') runWeb(q)
    else run(q, domain, status, limit)
  }, [mode, q, domain, status, limit, run, runWeb])

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
    if (initial.q && initial.mode === 'web') { runWeb(initial.q); return }
    if (initial.q) run(initial.q, initial.domain, '', 12)
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
        <div className="filter-row" style={{ marginBottom: 2 }}>
          <button
            className={`chip ${mode === 'local' ? 'active' : ''}`}
            onClick={() => setMode('local')}
          >
            本地库
            <span className="dim mono" style={{ fontSize: 10.5 }}>
              {overview?.stats?.documents ?? 0}
            </span>
          </button>
          <button
            className={`chip ${mode === 'web' ? 'active' : ''}`}
            onClick={() => setMode('web')}
          >
            联网搜索
            <span className="dim mono" style={{ fontSize: 10.5 }}>
              Bing
            </span>
          </button>
          <span style={{ fontSize: 11.5, color: 'var(--muted)', marginLeft: 4 }}>
            {mode === 'local'
              ? '检索已采集并结构化的事实与文档'
              : '本地库没有的内容，现场联网搜索；可一键收录进本地库'}
          </span>
        </div>

        <div className="search-row">
          <div className="search-input-wrap">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.2-3.2" />
            </svg>
            <input
              id="main-search"
              className="search-input"
              placeholder={
                mode === 'local'
                  ? '检索公告标题、项目名称、公司或金额…（按 / 聚焦）'
                  : '联网搜索任意内容，例如「大模型最新进展」…（按 / 聚焦）'
              }
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              autoFocus
            />
          </div>
          <button
            className="btn btn-primary"
            style={{ height: 50, padding: '0 22px' }}
            onClick={submit}
            disabled={(mode === 'local' ? loading : webLoading) || !q.trim()}
          >
            {mode === 'local' ? (loading ? <span className="spinner" /> : null)
                              : (webLoading ? <span className="spinner" /> : null)}
            {mode === 'local' ? '检索' : '联网'}
          </button>
        </div>

        {mode === 'local' ? (
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
        ) : null}
      </div>

      {error ? <div className="banner banner-danger">检索失败：{error}</div> : null}

      {mode === 'web' ? (
        <>
          {web ? (
            <>
              <div className="metric-grid">
                <div className="metric">
                  <div className="metric-label">联网命中</div>
                  <div className="metric-value">{web.results.length}</div>
                  <div className="metric-sub">引擎 {web.engine ?? '不可用'}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">耗时</div>
                  <div className="metric-value">{web.latency_ms}</div>
                  <div className="metric-sub">毫秒</div>
                </div>
                <div className="metric">
                  <div className="metric-label">已收录</div>
                  <div className="metric-value">{Object.keys(ingested).length}</div>
                  <div className="metric-sub">收录后本地库可搜到</div>
                </div>
                <div className="metric">
                  <div className="metric-label">错误</div>
                  <div className="metric-value" style={{ fontSize: 15 }}>
                    {web.errors.length ? web.errors[0].slice(0, 28) : '无'}
                  </div>
                  <div className="metric-sub">引擎降级链</div>
                </div>
              </div>

              <div className="result-list">
                {web.results.map((r, i) => (
                  <article className="result" key={r.url} style={{ cursor: 'default' }}>
                    <div className="result-title">
                      <span className="result-rank">#{i + 1}</span>
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: 'inherit', textDecoration: 'none' }}
                      >
                        {r.title}
                      </a>
                    </div>
                    <div className="result-snippet">{r.snippet || '（无摘要）'}</div>
                    <div className="result-meta">
                      <span className="tag tag-domain">{r.engine}</span>
                      <a className="url" href={r.url} target="_blank" rel="noreferrer">
                        {r.url.length > 76 ? r.url.slice(0, 76) + '…' : r.url}
                      </a>
                      <button
                        className="btn btn-sm"
                        style={{ marginLeft: 'auto' }}
                        onClick={() => doIngest(r.url)}
                        disabled={ingesting === r.url || Boolean(ingested[r.url])}
                      >
                        {ingesting === r.url ? <span className="spinner" /> : null}
                        {ingested[r.url] ? '已收录' : '收录到本地库'}
                      </button>
                    </div>
                  </article>
                ))}
                {web.results.length === 0 ? (
                  <div className="glass empty">
                    <div className="empty-badge">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                        <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z" />
                        <path d="M2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20" />
                      </svg>
                    </div>
                    <div>联网没有拿到结果</div>
                    <div style={{ fontSize: 12 }}>引擎返回：{web.errors.join(' / ') || '空'}</div>
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="glass empty">
              <div className="empty-badge">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z" />
                  <path d="M2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20" />
                </svg>
              </div>
              <div>输入任意关键词，联网搜索</div>
              <div style={{ fontSize: 12 }}>结果可直接收录进本地库，之后就能用本地检索查到</div>
            </div>
          )}
        </>
      ) : null}

      {mode === 'local' && data ? (
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
      ) : mode === 'web' ? null : (
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
