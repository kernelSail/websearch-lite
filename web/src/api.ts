const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.error ?? JSON.stringify(body)
    } catch {
      detail = await res.text()
    }
    throw new Error(`HTTP ${res.status} · ${detail}`)
  }
  return (await res.json()) as T
}

export const api = {
  overview: () => request<import('./types').Overview>('/api/overview'),
  search: (q: string, domain?: string, limit = 12, status?: string) => {
    const p = new URLSearchParams({ q, limit: String(limit) })
    if (domain) p.set('domain', domain)
    if (status) p.set('status', status)
    return request<import('./types').SearchResponse>(`/api/search?${p}`)
  },
  websearch: (q: string, limit = 10) => {
    const p = new URLSearchParams({ q, limit: String(limit) })
    return request<import('./types').WebSearchResponse>(`/api/websearch?${p}`)
  },
  ingest: (url: string) =>
    request<{ ok: boolean; error?: string; title?: string; document_id?: string; chars?: number }>(
      '/api/actions/ingest',
      { method: 'POST', body: JSON.stringify({ url }) },
    ),
  documents: (domain?: string, q?: string, limit = 40, offset = 0) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (domain) p.set('domain', domain)
    if (q) p.set('q', q)
    return request<{
      total: number
      limit: number
      offset: number
      documents: import('./types').DocumentRow[]
    }>(`/api/documents?${p}`)
  },
  document: (docId: string) =>
    request<import('./types').DocumentDetail>(`/api/documents/${encodeURIComponent(docId)}`),
  facts: (domain?: string, status?: string, limit = 120) => {
    const p = new URLSearchParams({ limit: String(limit) })
    if (domain) p.set('domain', domain)
    if (status) p.set('status', status)
    return request<{ facts: import('./types').FactRow[] }>(`/api/facts?${p}`)
  },
  conflicts: () => request<{ conflicts: import('./types').ConflictRow[] }>('/api/conflicts'),
  reviews: (limit = 80) =>
    request<{ reviews: import('./types').ReviewRow[] }>(`/api/reviews?limit=${limit}`),
  resolveConflict: (conflictId: string, winner: string, reason: string) =>
    request<{ ok: boolean; error?: string; status?: string }>('/api/conflicts/resolve', {
      method: 'POST',
      body: JSON.stringify({ conflict_id: conflictId, winner, reason }),
    }),
  verify: (domain?: string) =>
    request<{ ok: boolean; error?: string; result?: Record<string, number> }>('/api/actions/verify', {
      method: 'POST',
      body: JSON.stringify({ domain: domain ?? '' }),
    }),
  crawl: (domain?: string, maxPages?: number) =>
    request<{ ok: boolean; error?: string; result?: unknown }>('/api/actions/crawl', {
      method: 'POST',
      body: JSON.stringify({ domain: domain ?? '', max_pages: maxPages ?? null }),
    }),
  llm: () =>
    request<{ available: boolean; models?: string[]; model_present?: boolean; error?: string }>(
      '/api/llm',
    ),
}

/**
 * 深度检索：POST /api/research，服务端 SSE 推阶段事件，最后推 done。
 * 用 fetch + ReadableStream 读取（EventSource 不支持 POST）。
 */
export async function researchStream(
  question: string,
  onStage: (stage: import('./types').ResearchStage) => void,
  signal?: AbortSignal,
): Promise<import('./types').ResearchResponse> {
  const res = await fetch('/api/research', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: import('./types').ResearchResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      const lines = chunk.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      let payload: unknown
      try {
        payload = JSON.parse(data)
      } catch {
        continue
      }
      if (event === 'done') {
        final = payload as import('./types').ResearchResponse
      } else {
        onStage(payload as import('./types').ResearchStage)
      }
    }
  }
  return final ?? { ok: false, error: '流式响应未收到结果' }
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 19)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function shortId(id: string | null | undefined): string {
  if (!id) return '—'
  return id.length > 18 ? `${id.slice(0, 10)}…${id.slice(-4)}` : id
}
