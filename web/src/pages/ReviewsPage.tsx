import { useCallback, useEffect, useState } from 'react'
import { api, formatTime, shortId } from '../api'
import type { ReviewRow } from '../types'

export function ReviewsPage() {
  const [rows, setRows] = useState<ReviewRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api
      .reviews(200)
      .then((d) => {
        setRows(d.reviews)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const byType = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.task_type] = (acc[r.task_type] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>人工复核队列</h1>
          <p>低置信实体、验证冲突、任务重试耗尽等会自动进入队列，等待人工确认</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-sm" onClick={load} disabled={loading}>
            {loading ? <span className="spinner" /> : null}
            刷新
          </button>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">待处理</div>
          <div className="metric-value" style={{ color: rows.length ? 'var(--warn)' : 'var(--ok)' }}>
            {rows.length}
          </div>
          <div className="metric-sub">pending 任务</div>
        </div>
        {Object.entries(byType).slice(0, 3).map(([type, count]) => (
          <div className="metric" key={type}>
            <div className="metric-label">{type}</div>
            <div className="metric-value">{count}</div>
            <div className="metric-sub">按任务类型</div>
          </div>
        ))}
      </div>

      {error ? <div className="banner banner-danger">{error}</div> : null}

      {loading ? (
        <div className="glass glass-pad">
          <div className="skeleton" style={{ height: 16, marginBottom: 10 }} />
          <div className="skeleton" style={{ height: 16, width: '50%' }} />
        </div>
      ) : rows.length === 0 ? (
        <div className="glass empty">
          <div className="empty-badge">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M5 12l5 5L20 7" />
            </svg>
          </div>
          <div>复核队列为空</div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>类型</th>
                <th>目标</th>
                <th>原因</th>
                <th>优先级</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.review_task_id}>
                  <td>
                    <span className="tag tag-pending">{r.task_type}</span>
                  </td>
                  <td className="mono dim">
                    {r.target_type} · {shortId(r.target_id)}
                  </td>
                  <td style={{ maxWidth: 460, wordBreak: 'break-word' }}>{r.reason}</td>
                  <td className="mono">{r.priority}</td>
                  <td className="dim" style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                    {formatTime(r.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
