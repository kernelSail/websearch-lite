import { useEffect, useState } from 'react'
import { api, formatTime, shortId } from '../api'
import { DomainTag, PredicateTag, StatusTag } from './Tags'
import type { DocumentDetail } from '../types'

export function DocumentDrawer({ docId, onClose }: { docId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setError(null)
    api
      .document(docId)
      .then((d) => alive && setDetail(d))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [docId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2 className="drawer-title">{detail?.document?.title || '文档详情'}</h2>
            <div className="result-meta" style={{ marginTop: 6 }}>
              {detail?.document ? <DomainTag domain={detail.document.domain_id} /> : null}
              <span>{shortId(docId)}</span>
              <span>{formatTime(detail?.document?.fetched_at)}</span>
            </div>
          </div>
          <button className="btn btn-sm btn-ghost" onClick={onClose}>
            关闭
          </button>
        </div>

        {error ? <div className="banner banner-danger">加载失败：{error}</div> : null}
        {!detail && !error ? (
          <div style={{ display: 'grid', gap: 10 }}>
            <div className="skeleton" style={{ height: 14, width: '70%' }} />
            <div className="skeleton" style={{ height: 14, width: '92%' }} />
            <div className="skeleton" style={{ height: 90 }} />
          </div>
        ) : null}

        {detail?.found && detail.document ? (
          <>
            {detail.document.canonical_url ? (
              <a className="url" href={detail.document.canonical_url} target="_blank" rel="noreferrer">
                {detail.document.canonical_url}
              </a>
            ) : null}

            <div className="section-label">正文摘要</div>
            <div className="evidence">
              <div className="evidence-quote" style={{ borderLeft: 'none', paddingLeft: 0 }}>
                {detail.document.snippet || '（无摘要）'}
              </div>
            </div>

            <div className="section-label">版本</div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th>抓取时间</th>
                    <th>Hash</th>
                    <th>抽取</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.versions ?? []).map((v) => (
                    <tr key={v.document_version_id}>
                      <td className="mono">{shortId(v.document_version_id)}</td>
                      <td className="dim">{formatTime(v.fetched_at)}</td>
                      <td className="mono dim">{v.content_hash?.slice(0, 12) ?? '—'}</td>
                      <td className="dim">{v.extraction_status ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="section-label">证据与事实</div>
            {(detail.evidences ?? []).length === 0 ? (
              <div className="empty" style={{ padding: 26 }}>
                该文档暂未抽取到结构化事实
              </div>
            ) : (
              (detail.evidences ?? []).map((ev) => (
                <div className="evidence" key={ev.evidence_id}>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <PredicateTag predicate={ev.predicate} />
                    <StatusTag status={ev.verification_status} />
                    <span className="tag tag-pending">{ev.subject}</span>
                  </div>
                  <div className="evidence-quote">{ev.quoted_text}</div>
                  <div className="evidence-meta">
                    <span>
                      {ev.predicate} = {ev.normalized_value}
                    </span>
                    <span>
                      偏移 {ev.char_start}–{ev.char_end}
                    </span>
                    <span>{ev.fact_version_id}</span>
                  </div>
                </div>
              ))
            )}
          </>
        ) : null}

        {detail && !detail.found ? <div className="banner banner-warn">未找到该文档。</div> : null}
      </div>
    </div>
  )
}
