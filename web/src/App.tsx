import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { Overview } from './types'
import { ToastProvider } from './components/Toast'
import { SearchPage } from './pages/SearchPage'
import { FactsPage } from './pages/FactsPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { ReviewsPage } from './pages/ReviewsPage'
import { SystemPage } from './pages/SystemPage'

type Page = 'search' | 'facts' | 'conflicts' | 'reviews' | 'system'

const NAV: Array<{ key: Page; label: string }> = [
  { key: 'search', label: '检索' },
  { key: 'facts', label: '事实' },
  { key: 'conflicts', label: '冲突' },
  { key: 'reviews', label: '复核' },
  { key: 'system', label: '系统' },
]

const VALID: Page[] = ['search', 'facts', 'conflicts', 'reviews', 'system']

function pageFromHash(): Page {
  const raw = window.location.hash.replace(/^#\/?/, '')
  return (VALID as string[]).includes(raw) ? (raw as Page) : 'search'
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash())
  const [overview, setOverview] = useState<Overview | null>(null)
  const [offline, setOffline] = useState<string | null>(null)

  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = useCallback((next: Page) => {
    setPage(next)
    window.location.hash = `#/${next}`
  }, [])

  const reload = useCallback(() => {
    api
      .overview()
      .then((o) => {
        setOverview(o)
        setOffline(null)
      })
      .catch((e: Error) => setOffline(e.message))
  }, [])

  useEffect(() => {
    reload()
    const timer = window.setInterval(reload, 30000)
    return () => window.clearInterval(timer)
  }, [reload])

  const counts: Record<Page, number | undefined> = {
    search: undefined,
    facts: overview?.stats?.facts,
    conflicts: undefined,
    reviews: overview?.stats?.review_tasks,
    system: undefined,
  }

  return (
    <ToastProvider>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark" />
            <div className="brand-text">
              <b>WebSearch Lite</b>
              <span>定向检索控制台</span>
            </div>
          </div>

          <nav className="nav">
            <div className="nav-label">工作台</div>
            {NAV.map((item) => (
              <button
                key={item.key}
                className={`nav-item ${page === item.key ? 'active' : ''}`}
                onClick={() => go(item.key)}
              >
                <span className="dot" />
                {item.label}
                {counts[item.key] !== undefined ? (
                  <span className="count">{counts[item.key]}</span>
                ) : null}
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <div className="kv">
              <span>文档</span>
              <b>{overview?.stats?.documents ?? '—'}</b>
            </div>
            <div className="kv">
              <span>事实</span>
              <b>{overview?.stats?.fact_versions ?? '—'}</b>
            </div>
            <div className="kv">
              <span>实体</span>
              <b>{overview?.stats?.entities ?? '—'}</b>
            </div>
            <div className="kv">
              <span>引擎</span>
              <b>{overview?.engine ?? '—'}</b>
            </div>
            <div className="kv">
              <span>状态</span>
              <b style={{ color: offline ? 'var(--danger)' : 'var(--ok)' }}>
                {offline ? 'API 离线' : '在线'}
              </b>
            </div>
          </div>
        </aside>

        <main className="main">
          {offline ? (
            <div className="banner banner-danger">
              无法连接本地 API（{offline}）。请先在项目根目录运行：
              <code className="mono"> python -m websearch_lite.server</code>
            </div>
          ) : null}

          {page === 'search' ? <SearchPage overview={overview} /> : null}
          {page === 'facts' ? <FactsPage overview={overview} /> : null}
          {page === 'conflicts' ? <ConflictsPage /> : null}
          {page === 'reviews' ? <ReviewsPage /> : null}
          {page === 'system' ? <SystemPage overview={overview} reload={reload} /> : null}
        </main>
      </div>
    </ToastProvider>
  )
}
