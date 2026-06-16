import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, BookOpen } from 'lucide-react'
import { api, fmtDate } from '../api'
import BatchGenerate from '../components/BatchGenerate'

const STATUS_TABS = [
  { key: '',         label: '全部' },
  { key: 'reading',  label: '在读' },
  { key: 'finished', label: '已读完' },
  { key: 'unread',   label: '未开始' },
]

const SORT_OPTIONS = [
  { key: 'engaged',     label: '综合（划线/读完优先）' },
  { key: 'last_read',   label: '最近阅读' },
  { key: 'finish_time', label: '完读时间' },
  { key: 'highlights',  label: '划线最多' },
]

function BookCard({ book }) {
  const finished = !!book.finish_time

  return (
    <Link to={`/books/${book.book_id}`}
      className="bg-surface rounded-2xl border border-line shadow-card p-4 hover:shadow-md hover:border-clay/20 transition-all block">
      <div className="flex gap-3.5">
        {book.cover ? (
          <img src={book.cover} alt={book.title}
            className="w-12 h-[68px] object-cover rounded-md flex-shrink-0 border border-line" />
        ) : (
          <div className="w-12 h-[68px] rounded-md bg-clay-soft border border-line flex items-center justify-center flex-shrink-0">
            <BookOpen className="w-4 h-4 text-clay" strokeWidth={1.5} />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="reading text-[15px] font-medium text-ink leading-snug line-clamp-2">{book.title}</p>
          <p className="text-xs text-ink-faint mt-1 truncate">{book.author}</p>
          <div className="flex items-center gap-2 mt-2">
            {finished ? (
              <span className="text-xs bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded">已读完</span>
            ) : book.highlight_count > 0 ? (
              <span className="text-xs bg-clay-soft text-clay-ink px-1.5 py-0.5 rounded">在读</span>
            ) : (
              <span className="text-xs bg-paper text-ink-faint px-1.5 py-0.5 rounded">未开始</span>
            )}
            {book.category && (
              <span className="text-xs text-ink-faint truncate">{book.category}</span>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3 mt-3.5 pt-3 border-t border-line text-xs text-ink-faint">
        <span className={book.highlight_count ? 'text-ink-soft' : ''}>{book.highlight_count || 0} 划线</span>
        <span className={book.review_count ? 'text-ink-soft' : ''}>{book.review_count || 0} 批注</span>
        {finished && book.finish_time && (
          <span className="ml-auto">{fmtDate(book.finish_time)}</span>
        )}
        {!finished && book.last_read_time && (
          <span className="ml-auto">{fmtDate(book.last_read_time)}</span>
        )}
      </div>
    </Link>
  )
}

export default function Books() {
  const [books, setBooks]   = useState([])
  const [status, setStatus] = useState('')
  const [sort, setSort]     = useState('engaged')
  const [q, setQ]           = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [loading, setLoading] = useState(true)

  // debounce 输入，避免逐字符请求
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    setLoading(true)
    const params = { sort }
    if (status)     params.status = status
    if (debouncedQ) params.q = debouncedQ
    api.books(params).then(setBooks).finally(() => setLoading(false))
  }, [status, sort, debouncedQ])

  return (
    <div className="px-6 md:px-10 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-ink mb-6">书架</h1>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
          <input
            type="text"
            placeholder="搜索书名 / 作者"
            value={q}
            onChange={e => setQ(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm border border-line rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-clay/30 w-52"
          />
        </div>

        <div className="flex gap-1 bg-paper border border-line p-0.5 rounded-lg">
          {STATUS_TABS.map(t => (
            <button key={t.key} onClick={() => setStatus(t.key)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                status === t.key ? 'bg-surface text-ink shadow-sm font-medium' : 'text-ink-soft hover:text-ink'
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        <select value={sort} onChange={e => setSort(e.target.value)}
          className="ml-auto text-xs border border-line rounded-lg px-2 py-1.5 bg-surface focus:outline-none text-ink-soft">
          {SORT_OPTIONS.map(o => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-6 mb-4">
        <p className="text-xs text-ink-faint">{books.length} 本</p>
        <BatchGenerate />
      </div>

      {loading ? (
        <div className="text-sm text-ink-faint">加载中…</div>
      ) : books.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
          {books.map(b => <BookCard key={b.book_id} book={b} />)}
        </div>
      ) : (
        <div className="text-center py-16 text-sm text-ink-faint">没有符合条件的书籍</div>
      )}
    </div>
  )
}
