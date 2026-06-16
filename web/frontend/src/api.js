// 包一层 fetch：localhost 下的网络失败 = 后端服务没了（应用已关/离开太久被回收）。
// 广播事件让 App 弹"请重新打开应用"，而不是把生硬的 Failed to fetch 抛给用户。
async function _fetch(path, opts) {
  try {
    return await fetch(path, opts)
  } catch (e) {
    try { window.dispatchEvent(new Event('weread-backend-down')) } catch {}
    throw e
  }
}

async function get(path) {
  const res = await _fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

async function post(path) {
  const res = await _fetch(path, { method: 'POST' })
  if (!res.ok) {
    let detail = `${res.status}`
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  stats:          ()              => get('/api/stats'),
  books:          (params = {})  => get('/api/books?' + new URLSearchParams(params)),
  book:           (id)           => get(`/api/books/${id}`),
  timeline:       ()             => get('/api/timeline'),
  categories:     ()             => get('/api/categories'),
  search:         (q, limit=30)  => get(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  echoes:         (q, limit=10)  => get(`/api/echoes?q=${encodeURIComponent(q)}&limit=${limit}`),
  recentActivity: (days=30)      => get(`/api/recent_activity?days=${days}`),
  insight: {
    connections: (limit=3) => get(`/api/insight/connections?limit=${limit}`),
    reread:      ()        => get('/api/insight/reread'),
    themes:      (days=30) => get(`/api/insight/themes?days=${days}`),
  },
  capabilities:  ()                => get('/api/capabilities'),
  summarizeBook: (id, force=false) => post(`/api/books/${id}/summarize?force=${force}`),
  saveBookSummary: (id, content) => postJson(`/api/books/${id}/summary`, { content }),
  getLlmSettings: () => get('/api/settings/llm'),
  saveLlmSettings: (cfg) => postJson('/api/settings/llm', cfg),
  sync: () => post('/api/sync'),
  backfillStart:  (kind, force=false) => post(`/api/backfill/start?kind=${kind}&force=${force}`),
  extractBookConcepts: (id) => post(`/api/books/${id}/concepts`),
  backfillStop:   ()     => post('/api/backfill/stop'),
  backfillStatus: ()     => get('/api/backfill/status'),
  backfillPending: ()    => get('/api/backfill/pending'),
  graph:        ()    => get('/api/graph'),
  graphConcept: (tag) => get(`/api/graph/concept/${encodeURIComponent(tag)}`),
  explore:      (q, limit=20) => get(`/api/explore?q=${encodeURIComponent(q)}&limit=${limit}`),
  // 首启向导（仅 standalone 版 setup_api 提供；dev/agent 版无此路由 → 调用方按 404 当已配置处理）
  apikeyStatus:  () => get('/api/settings/apikey'),
  saveApikey:    (key) => postJson('/api/settings/apikey', { api_key: key }),
  fullSyncStart: () => post('/api/sync/full/start'),
  fullSyncStatus:() => get('/api/sync/full/status'),
  shutdown:      () => post('/api/shutdown'),
  heartbeat:     () => post('/api/heartbeat'),
}

async function postJson(path, body) {
  const res = await _fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export function fmtDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
}

export function daysAgo(ts) {
  if (!ts) return ''
  const d = Math.floor((Date.now() / 1000 - ts) / 86400)
  if (d === 0) return '今天'
  if (d === 1) return '昨天'
  if (d < 30)  return `${d} 天前`
  if (d < 365) return `${Math.floor(d / 30)} 个月前`
  return `${Math.floor(d / 365)} 年前`
}
