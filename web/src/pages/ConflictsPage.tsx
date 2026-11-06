import { useCallback, useEffect, useState } from 'react'
import { api, formatTime, shortId } from '../api'
import type { ConflictRow } from '../types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useToast } from '../components/Toast'

interface Snapshot {
  fact_id?: string
  current?: { fact_version_id: string; value: string }
  competing?: Array<{ fact_version_id: string; value: string }>
  components?: Record<string, unknown>
  decided_at?: string
}

function parseSnapshot(raw: string): Snapshot {
  try {
    return JSON.parse(raw) as Snapshot
  } catch {
    return {}
  }
}

export function ConflictsPage() {
  const [rows, setRows] = useState<ConflictRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<{ conflict: ConflictRow; winner: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const load = useCallback(() => {
    setLoading(true)
    api
      .conflicts()
      .then((d) => {
        setRows(d.conflicts)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const doResolve = async () => {
    if (!pending) return
    setBusy(true)
    try {
      const res = await api.resolveConflict(
        pending.conflict.conflict_id,
        pending.winner,
        '由 Web 控制台人工裁决',
      )
      if (res.ok) {
        toast.push('ok', `冲突 ${shortId(pending.conflict.conflict_id)} 已裁决`)
        setPending(null)
        load()
      } else {
        toast.push('err', res.error ?? '裁决失败')
      }
    } catch (e) {
      toast.push('err', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const open = rows.filter((r) => r.status === 'open')
  const resolved = rows.filter((r) => r.status !== 'open')

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>冲突与裁决</h1>
          <p>同一事实出现不同取值时保留双版本快照，不静默覆盖；裁决需显式指定胜出版本</p>
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
          <div className="metric-label">待裁决</div>
          <div className="metric-value" style={{ color: open.length ? 'var(--danger)' : 'var(--ok)' }}>
            {open.length}
          </div>
          <div className="metric-sub">open 状态</div>
        </div>
        <div className="metric">
          <div className="metric-label">已裁决</div>
          <div className="metric-value">{resolved.length}</div>
          <div className="metric-sub">保留裁决理由与时间</div>
        </div>
        <div className="metric">
          <div className="metric-label">冲突总数</div>
          <div className="metric-value">{rows.length}</div>
          <div className="metric-sub">含历史</div>
        </div>
      </div>

      {error ? <div className="banner banner-danger">{error}</div> : null}

      {loading ? (
        <div className="glass glass-pad">
          <div className="skeleton" style={{ height: 16, marginBottom: 10 }} />
          <div className="skeleton" style={{ height: 16, width: '60%' }} />
        </div>
      ) : rows.length === 0 ? (
        <div className="glass empty">
          <div className="empty-badge">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M5 12l5 5L20 7" />
            </svg>
          </div>
          <div>当前没有冲突记录</div>
          <div style={{ fontSize: 12 }}>同一事实出现多来源不同取值时会自动生成快照</div>
        </div>
      ) : (
        <div className="result-list">
          {rows.map((c) => {
            const snap = parseSnapshot(c.conflict_snapshot_json)
            const current = snap.current
            const competing = snap.competing ?? []
            return (
              <div className="glass glass-pad" key={c.conflict_id}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className={`tag ${c.status === 'open' ? 'tag-conflict' : 'tag-verified'}`}>
                    {c.status === 'open' ? '待裁决' : '已裁决'}
                  </span>
                  <span className="mono dim">{shortId(c.conflict_id)}</span>
                  <span className="dim" style={{ fontSize: 12 }}>
                    {formatTime(c.created_at)}
                  </span>
                  {c.decided_by ? (
                    <span className="tag tag-pending">裁决人 {c.decided_by}</span>
                  ) : null}
                </div>

                <div className="grid-2" style={{ marginTop: 14 }}>
                  <div>
                    <div className="section-label" style={{ marginTop: 0 }}>
                      当前值
                    </div>
                    <div className="evidence">
                      <div className="evidence-quote" style={{ borderLeft: 'none', paddingLeft: 0 }}>
                        {current?.value ?? '—'}
                      </div>
                      <div className="evidence-meta">{shortId(current?.fact_version_id)}</div>
                    </div>
                  </div>
                  <div>
                    <div className="section-label" style={{ marginTop: 0 }}>
                      竞争值
                    </div>
                    {competing.length === 0 ? (
                      <div className="dim" style={{ fontSize: 12 }}>
                        —
                      </div>
                    ) : (
                      competing.map((v) => (
                        <div className="evidence" key={v.fact_version_id}>
                          <div className="evidence-quote" style={{ borderLeft: 'none', paddingLeft: 0 }}>
                            {v.value}
                          </div>
                          <div className="evidence-meta">
                            <span>{shortId(v.fact_version_id)}</span>
                            {c.status === 'open' ? (
                              <button
                                className="btn btn-sm"
                                onClick={() => setPending({ conflict: c, winner: v.fact_version_id })}
                              >
                                选为胜出
                              </button>
                            ) : null}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {c.decision_reason ? (
                  <div className="banner banner-info" style={{ marginTop: 12 }}>
                    {c.decision_reason}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {pending ? (
        <ConfirmDialog
          title="确认裁决该冲突？"
          description={`将把版本 ${pending.winner} 标记为 verified，另一版本保留在快照中。此操作会写入裁决记录，不可自动回滚。`}
          confirmText="确认裁决"
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={doResolve}
        />
      ) : null}
    </>
  )
}
