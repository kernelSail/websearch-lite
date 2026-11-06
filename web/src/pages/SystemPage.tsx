import { useState } from 'react'
import { api, formatTime, shortId } from '../api'
import type { Overview } from '../types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useToast } from '../components/Toast'
import { DomainTag, StatusTag } from '../components/Tags'

export function SystemPage({ overview, reload }: { overview: Overview | null; reload: () => void }) {
  const [confirm, setConfirm] = useState<'crawl' | 'verify' | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)
  const toast = useToast()

  const runAction = async () => {
    if (!confirm) return
    setBusy(true)
    try {
      if (confirm === 'crawl') {
        const res = await api.crawl(undefined, 4)
        if (res.ok) {
          toast.push('ok', '采集完成')
          setLastResult(JSON.stringify(res.result, null, 2))
          reload()
        } else {
          toast.push('err', res.error ?? '采集失败')
        }
      } else {
        const res = await api.verify()
        if (res.ok) {
          toast.push('ok', '验证完成')
          setLastResult(JSON.stringify(res.result, null, 2))
          reload()
        } else {
          toast.push('err', res.error ?? '验证失败')
        }
      }
      setConfirm(null)
    } catch (e) {
      toast.push('err', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const stats = overview?.stats ?? {}
  const verification = overview?.verification ?? {}

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>系统状态</h1>
          <p>存储、索引一致性、来源健康与后台动作入口</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-sm" onClick={reload}>
            刷新
          </button>
          <button className="btn btn-sm" onClick={() => setConfirm('verify')}>
            触发验证
          </button>
          <button className="btn btn-sm btn-primary" onClick={() => setConfirm('crawl')}>
            触发采集
          </button>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">文档</div>
          <div className="metric-value">{stats.documents ?? 0}</div>
          <div className="metric-sub">已索引 {stats.indexed_documents ?? 0}</div>
        </div>
        <div className="metric">
          <div className="metric-label">事实版本</div>
          <div className="metric-value">{stats.fact_versions ?? 0}</div>
          <div className="metric-sub">证据 {stats.fact_evidences ?? 0} 条</div>
        </div>
        <div className="metric">
          <div className="metric-label">实体</div>
          <div className="metric-value">{stats.entities ?? 0}</div>
          <div className="metric-sub">事实 {stats.facts ?? 0} 个</div>
        </div>
        <div className="metric">
          <div className="metric-label">索引一致性</div>
          <div
            className="metric-value"
            style={{ color: (overview?.consistency?.missing_index?.length ?? 0) ? 'var(--danger)' : 'var(--ok)' }}
          >
            {(overview?.consistency?.missing_index?.length ?? 0) ? 'MISMATCH' : 'OK'}
          </div>
          <div className="metric-sub">
            缺失 {overview?.consistency?.missing_index?.length ?? 0} · 版本不符{' '}
            {overview?.consistency?.version_mismatch?.length ?? 0}
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            验证状态分布
          </div>
          {Object.keys(verification).length === 0 ? (
            <div className="dim">暂无数据</div>
          ) : (
            Object.entries(verification).map(([k, v]) => (
              <div
                key={k}
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 9 }}
              >
                <StatusTag status={k} />
                <div
                  style={{
                    flex: 1,
                    height: 6,
                    borderRadius: 999,
                    background: 'rgba(255,255,255,.06)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min(100, (v / Math.max(1, Object.values(verification).reduce((a, b) => a + b, 0))) * 100)}%`,
                      height: '100%',
                      background: 'linear-gradient(90deg, var(--accent), var(--accent-2))',
                    }}
                  />
                </div>
                <span className="mono dim" style={{ width: 34, textAlign: 'right' }}>
                  {v}
                </span>
              </div>
            ))
          )}

          <div className="section-label">运行环境</div>
          <div className="kv">
            <span>检索引擎</span>
            <b>{overview?.engine ?? '—'}</b>
          </div>
          <div className="kv">
            <span>分类器</span>
            <b>{overview?.classifier ?? '—'}</b>
          </div>
          <div className="kv">
            <span>临时缓存</span>
            <b>入库即删</b>
          </div>
        </div>

        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            来源健康
          </div>
          {(overview?.sources ?? []).map((s) => (
            <div
              key={s.source_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 0',
                borderBottom: '1px solid rgba(120,150,220,.08)',
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: s.consecutive_failures > 0 ? 'var(--danger)' : 'var(--ok)',
                  boxShadow: `0 0 8px ${s.consecutive_failures > 0 ? 'var(--danger)' : 'var(--ok)'}`,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13 }}>{s.name || s.source_id}</div>
                <div className="dim mono" style={{ fontSize: 11 }}>
                  最近成功 {formatTime(s.last_success_at)}
                </div>
              </div>
              <span className="mono dim" style={{ fontSize: 11 }}>
                失败 {s.consecutive_failures}
              </span>
            </div>
          ))}

          <div className="section-label">最近运行</div>
          {(overview?.recent_runs ?? []).slice(0, 4).map((r) => (
            <div className="kv" key={r.run_id} style={{ padding: '4px 0' }}>
              <span className="mono dim" style={{ fontSize: 11 }}>
                {shortId(r.run_id)}
              </span>
              <b style={{ fontSize: 11 }}>{formatTime(r.started_at)}</b>
            </div>
          ))}
        </div>
      </div>

      <div className="glass glass-pad">
        <div className="section-label" style={{ marginTop: 0 }}>
          最近入库
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>标题</th>
                <th>域</th>
                <th>抓取时间</th>
              </tr>
            </thead>
            <tbody>
              {(overview?.recent_documents ?? []).map((d) => (
                <tr key={d.doc_id}>
                  <td style={{ maxWidth: 520, wordBreak: 'break-word' }}>{d.title || '（无标题）'}</td>
                  <td>
                    <DomainTag domain={d.domain_id} />
                  </td>
                  <td className="dim" style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                    {formatTime(d.fetched_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {lastResult ? (
        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            上次动作结果
          </div>
          <pre className="mono dim" style={{ fontSize: 11.5, whiteSpace: 'pre-wrap', margin: 0 }}>
            {lastResult}
          </pre>
        </div>
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={confirm === 'crawl' ? '确认触发一次采集？' : '确认对全部事实重新验证？'}
          description={
            confirm === 'crawl'
              ? '将对两个域各抓取最多 4 页，遵守 robots 与限速。会写入数据库，可能耗时数十秒。'
              : '会重新计算所有事实版本的验证状态，可能把 single-source 迁移为 verified/conflicting，并生成复核任务。'
          }
          confirmText={confirm === 'crawl' ? '开始采集' : '开始验证'}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={runAction}
        />
      ) : null}
    </>
  )
}
