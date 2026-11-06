import { useCallback, useEffect, useRef, useState } from 'react'
import { researchStream } from '../api'
import type { ResearchResponse, ResearchStage } from '../types'
import { useToast } from '../components/Toast'

const STAGE_LABEL: Record<string, string> = {
  search_start: '联网搜索中…',
  search_done: '搜索完成',
  fetch_start: '抓取网页正文…',
  fetch_one: '抓取',
  fetch_done: '抓取完成',
  local_done: '合并本地资料',
  llm_start: '模型阅读并总结…',
  llm_done: '总结完成',
  llm_error: '模型出错',
}

const EXAMPLES = [
  '大模型最新的进展有哪些？',
  'DeepSeek 最新模型有什么特点？',
  '2026 年政府采购有哪些新政策？',
]

export function ResearchPage() {
  const [question, setQuestion] = useState('')
  const [stages, setStages] = useState<ResearchStage[]>([])
  const [result, setResult] = useState<ResearchResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const toast = useToast()

  useEffect(() => {
    if (!running) return
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500)
    return () => window.clearInterval(timer)
  }, [running])

  const start = useCallback(
    async (q: string) => {
      if (!q.trim() || running) return
      setStages([])
      setResult(null)
      setRunning(true)
      setElapsed(0)
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const out = await researchStream(
          q,
          (stage) => setStages((prev) => [...prev, stage]),
          controller.signal,
        )
        setResult(out)
        if (!out.ok) toast.push('err', out.error ?? '总结失败')
        else toast.push('ok', `完成，用时 ${((out.elapsed_ms ?? 0) / 1000).toFixed(1)}s`)
      } catch (e) {
        if ((e as Error).name === 'AbortError') {
          toast.push('err', '已取消')
        } else {
          toast.push('err', (e as Error).message)
        }
      } finally {
        setRunning(false)
        abortRef.current = null
      }
    },
    [running, toast],
  )

  const stop = () => {
    abortRef.current?.abort()
  }

  const answer = result?.answer ?? ''
  const sources = result?.sources ?? []
  const citations = new Set(result?.citations ?? [])

  return (
    <>
      <div className="page-head">
        <div className="page-title">
          <h1>深度检索</h1>
          <p>联网搜索 → 抓取正文 → 本地模型阅读并总结，每条结论标注来源编号</p>
        </div>
        <div className="head-actions">
          {running ? (
            <button className="btn btn-sm" onClick={stop}>
              取消
            </button>
          ) : null}
        </div>
      </div>

      <div className="glass search-hero">
        <div className="search-row">
          <div className="search-input-wrap">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5l3 2" />
            </svg>
            <input
              className="search-input"
              placeholder="问一个问题，系统联网找资料并总结…"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') start(question)
              }}
              disabled={running}
            />
          </div>
          <button
            className="btn btn-primary"
            style={{ height: 50, padding: '0 22px' }}
            onClick={() => start(question)}
            disabled={running || !question.trim()}
          >
            {running ? <span className="spinner" /> : null}
            {running ? '思考中' : '开始'}
          </button>
        </div>
        <div className="filter-row">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              className="chip"
              disabled={running}
              onClick={() => {
                setQuestion(ex)
                start(ex)
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {stages.length > 0 ? (
        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            执行过程
            {running ? (
              <span className="dim mono" style={{ fontSize: 11, marginLeft: 10 }}>
                {elapsed}s
              </span>
            ) : null}
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {stages.map((s, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  gap: 10,
                  alignItems: 'center',
                  fontSize: 12.5,
                  color: s.stage === 'llm_error' ? 'var(--danger)' : 'var(--text-dim)',
                }}
              >
                <span className="mono dim" style={{ width: 58, textAlign: 'right' }}>
                  {(s.elapsed_ms / 1000).toFixed(1)}s
                </span>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }} />
                {STAGE_LABEL[s.stage] ?? s.stage}
                {s.stage === 'search_done' ? (
                  <span className="dim">
                    {String(s.engine ?? '')} · {String(s.count ?? 0)} 条
                  </span>
                ) : null}
                {s.stage === 'fetch_one' ? (
                  <span className="mono dim" style={{ fontSize: 11 }}>
                    {String(s.url ?? '').slice(0, 60)} {s.ok ? '✓' : '✗'}
                  </span>
                ) : null}
                {s.stage === 'llm_start' ? (
                  <span className="dim">
                    {String(s.model ?? '')} · {String(s.sources ?? 0)} 篇资料
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {answer ? (
        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            总结
            {result?.model ? (
              <span className="tag tag-domain" style={{ marginLeft: 'auto' }}>
                {result.model}
              </span>
            ) : null}
          </div>
          <div style={{ fontSize: 14.5, lineHeight: 1.85, whiteSpace: 'pre-wrap' }}>{answer}</div>
          {(result?.invalid_citations?.length ?? 0) > 0 ? (
            <div className="banner banner-warn" style={{ marginTop: 14 }}>
              模型引用了不存在的编号 {result?.invalid_citations?.join(', ')}，请核对来源。
            </div>
          ) : null}
          {citations.size > 0 ? (
            <div className="result-meta" style={{ marginTop: 14 }}>
              引用编号：
              {[...citations].sort((a, b) => a - b).map((c) => (
                <span key={c} className="tag tag-fact">
                  [{c}]
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {sources.length > 0 ? (
        <div className="glass glass-pad">
          <div className="section-label" style={{ marginTop: 0 }}>
            来源
            <span className="dim mono" style={{ fontSize: 11, marginLeft: 'auto' }}>
              {sources.length} 篇
            </span>
          </div>
          <div style={{ display: 'grid', gap: 2 }}>
            {sources.map((s) => (
              <div
                key={s.index}
                style={{
                  display: 'flex',
                  gap: 10,
                  alignItems: 'baseline',
                  padding: '9px 4px',
                  borderBottom: '1px solid rgba(120,150,220,.07)',
                }}
              >
                <span
                  className="mono"
                  style={{ color: citations.has(s.index) ? 'var(--accent)' : 'var(--muted)', width: 26 }}
                >
                  [{s.index}]
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.title || '(无标题)'}
                  </div>
                  {s.url ? (
                    <a className="url" href={s.url} target="_blank" rel="noreferrer">
                      {s.url.length > 78 ? s.url.slice(0, 78) + '…' : s.url}
                    </a>
                  ) : null}
                </div>
                <span className={`tag ${s.origin === 'local' ? 'tag-single' : 'tag-pending'}`}>
                  {s.origin === 'local' ? '本地库' : '网抓'}
                </span>
                {s.chars ? (
                  <span className="mono dim" style={{ fontSize: 11 }}>
                    {s.chars} 字
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {!running && !result ? (
        <div className="glass empty">
          <div className="empty-badge">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" />
              <path d="M8 12h8M12 8v8" />
            </svg>
          </div>
          <div>问一个问题，系统会联网找资料、读正文、再总结</div>
          <div style={{ fontSize: 12 }}>
            依赖本地 Ollama 模型；CPU 推理下每次约 1–3 分钟，请耐心等待阶段进度
          </div>
        </div>
      ) : null}
    </>
  )
}
