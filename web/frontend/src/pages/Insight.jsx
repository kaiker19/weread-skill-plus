import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { api, daysAgo, fmtDate } from '../api'

function todayLabel() {
  const d = new Date()
  const wd = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1}月${d.getDate()}日 · ${wd}`
}

/* 跨书连接 — 招牌对照卡 */
function ConnectionCard({ pair }) {
  const { anchor, echo, similarity } = pair
  return (
    <div className="bg-surface rounded-2xl border border-line shadow-card p-7">
      <Quote item={anchor} note={anchor.days_ago === 0 ? '今天划' : `${anchor.days_ago} 天前划`} />
      <div className="flex items-center gap-3 my-5 text-clay">
        <span className="h-px flex-1 bg-line" />
        <span className="text-xs tracking-widest">⟡ 呼应</span>
        <span className="h-px flex-1 bg-line" />
      </div>
      <Quote item={echo} note={`${echo.days_ago} 天前`} />
      <div className="mt-4 text-right">
        <span className="text-xs bg-clay-soft text-clay-ink px-2 py-0.5 rounded">语义 {Math.round(similarity * 100)}%</span>
      </div>
    </div>
  )
}

function Quote({ item, note }) {
  return (
    <div>
      <p className="reading text-[17px] text-ink leading-[1.9]">{item.content}</p>
      <Link to={`/books/${item.book_id}`}
        className="inline-block mt-2 text-xs text-ink-faint hover:text-clay">
        —《{item.book_title}》· {note}
      </Link>
    </div>
  )
}

/* 每日重读卡 */
function RereadCard({ item }) {
  return (
    <div className="bg-surface rounded-2xl border border-line shadow-card p-6 h-full">
      <h2 className="text-xs font-medium text-clay/80 tracking-wide mb-3">重读</h2>
      <p className="reading text-[15px] text-ink leading-[1.85]">{item.content}</p>
      <Link to={`/books/${item.book_id}`}
        className="inline-block mt-3 text-xs text-ink-faint hover:text-clay">
        《{item.book_title}》· {item.days_ago} 天前
      </Link>
      {item.why?.anchor_book_title && (
        <p className="text-xs text-ink-faint mt-2">呼应你在读的《{item.why.anchor_book_title}》</p>
      )}
    </div>
  )
}

/* 最近主题 */
function ThemesCard({ themes }) {
  return (
    <div className="bg-surface rounded-2xl border border-line shadow-card p-6 h-full">
      <h2 className="text-xs font-medium text-clay/80 tracking-wide mb-1">最近在想</h2>
      <p className="text-[11px] text-ink-faint mb-3">按语义把近 30 天的划线聚成几簇，代表句如下（概念命名待后续）</p>
      <ul className="space-y-3">
        {themes.map((t, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-clay/50 text-xs mt-1">·</span>
            <div className="min-w-0">
              <p className="reading text-[13.5px] text-ink leading-snug line-clamp-2">{t.label_content}</p>
              <span className="text-xs text-ink-faint">这簇含 {t.count} 条划线 · 跨 {t.book_count} 本书</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function EmptyHint({ children }) {
  return <div className="bg-surface rounded-2xl border border-dashed border-line p-6 text-sm text-ink-faint">{children}</div>
}

export default function Insight() {
  const [stats, setStats] = useState(null)
  const [allConns, setAllConns] = useState([])   // 整池强连接，前端轮转显示
  const [offset, setOffset] = useState(0)
  const [reread, setReread] = useState(null)
  const [themes, setThemes] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)

  const load = () => Promise.all([
    api.stats(),
    api.insight.connections(8),   // 取回整池：都 ≥ 阈值（相关性有保证），前端轮转
    api.insight.reread(),
    api.insight.themes(),
  ]).then(([s, c, r, t]) => { setStats(s); setAllConns(c); setOffset(0); setReread(r); setThemes(t) })

  useEffect(() => { load().finally(() => setLoading(false)) }, [])

  const onSync = () => {
    setSyncing(true)
    api.sync()
      .then(() => load())
      .catch(e => alert('同步失败：' + e.message))
      .finally(() => setSyncing(false))
  }

  // 打开应用时，若上次同步距今超过 12 小时，自动增量同步一次（拉今天新读的 + 嵌入 + 刷新呼应）
  const autoSynced = useRef(false)
  useEffect(() => {
    if (autoSynced.current || syncing || !stats?.last_sync_ts) return
    if (Date.now() / 1000 - stats.last_sync_ts > 12 * 3600) {
      autoSynced.current = true
      onSync()
    }
  }, [stats])

  // 「换一批」轮转到下一组（纯前端、瞬时；都来自同一批 ≥阈值 的强连接，故每次都相关又不同）
  const SHOW = 2
  const shuffle = () => setOffset(o => (o + SHOW) % allConns.length)

  if (loading) return <div className="p-10 text-sm text-ink-faint">加载中…</div>

  const conns = allConns.length <= SHOW
    ? allConns
    : Array.from({ length: SHOW }, (_, i) => allConns[(offset + i) % allConns.length])
  const canShuffle = allConns.length > SHOW
  const hasVectors = allConns.length > 0 || reread || themes.length > 0

  return (
    <div className="px-8 py-10 max-w-[720px] mx-auto">
      <div className="flex items-baseline justify-between mb-1">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">洞见</h1>
        <span className="text-xs text-ink-faint">{todayLabel()}</span>
      </div>
      {stats && (
        <div className="flex items-center gap-3 mb-9">
          <p className="text-xs text-ink-faint">
            {stats.books_total} 本 · {stats.highlights} 划线 · {stats.reviews} 批注 · {stats.books_finished} 读完
          </p>
          <div className="ml-auto flex items-center gap-2 text-xs">
            {stats.last_sync_ts && (
              <span className="text-ink-faint hidden sm:inline">上次同步 {fmtDate(stats.last_sync_ts)}</span>
            )}
            <button onClick={onSync} disabled={syncing}
              className="flex items-center gap-1 text-clay hover:text-clay-ink disabled:opacity-50">
              <RefreshCw className={`w-3 h-3 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? '同步中…' : '同步最新'}
            </button>
          </div>
        </div>
      )}

      {!hasVectors && (
        <EmptyHint>
          语义连接还在路上。点右上角「同步最新」拉取并建立语义索引后，
          这里会浮现跨书呼应、值得重读的旧划线，和你最近在想的主题。
        </EmptyHint>
      )}

      {/* 跨书连接 — 主角 */}
      {conns.length > 0 && (
        <section className="mb-10">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-medium text-ink-soft">近期呼应</h2>
            {canShuffle && (
              <button onClick={shuffle}
                className="flex items-center gap-1 text-xs text-ink-faint hover:text-clay">
                <RefreshCw className="w-3 h-3" /> 换一批
              </button>
            )}
          </div>
          <p className="text-xs text-ink-faint mb-4">你最近读到的，与历史里某本书的划线遥相呼应</p>
          <div className="space-y-4">
            {conns.map((p, i) => <ConnectionCard key={i} pair={p} />)}
          </div>
        </section>
      )}

      {/* 重读 + 最近主题 */}
      {(reread || themes.length > 0) && (
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {reread && <RereadCard item={reread} />}
          {themes.length > 0 && <ThemesCard themes={themes} />}
        </section>
      )}
    </div>
  )
}
