import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Bookmark, MessageSquare, CornerDownLeft } from 'lucide-react'
import { api } from '../api'

/* 写作台：边写边浮现你过去的划线/批注（语义检索，零 LLM）。
   右栏随当前段落实时更新；点一条即在光标处插入为引用。 */

// 检索探针：光标所在段落，但只取最近一段（≤140字、从最近句末起），
// 避免长段落超出向量模型上下文、语义被稀释导致检索漂移
function probeText(text, caret) {
  const para = text.slice(0, caret).split(/\n\s*\n/).pop().trim()
  if (para.length <= 140) return para
  const tail = para.slice(-140)
  const m = tail.search(/[。！？.!?；;]\s*/)
  return (m >= 0 ? tail.slice(m + 1) : tail).trim()
}

function SurfaceCard({ item, onInsert }) {
  const isReview = item.source_type === 'review'
  const pct = item.similarity != null ? Math.round(item.similarity * 100) : null
  return (
    <button onClick={() => onInsert(item)}
      className="group w-full text-left bg-surface rounded-xl border border-line shadow-card px-3.5 py-3 hover:border-clay/50 hover:shadow-sm transition">
      <p className="reading text-[13px] text-ink leading-[1.75] line-clamp-4">{item.content}</p>
      <div className="flex items-center gap-2 mt-2">
        <span className={`inline-flex items-center gap-1 text-[10.5px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 ${
          isReview ? 'bg-amber-50 text-amber-600' : 'bg-clay-soft text-clay-ink'}`}>
          {isReview ? <MessageSquare className="w-2.5 h-2.5 shrink-0" /> : <Bookmark className="w-2.5 h-2.5 shrink-0" />}
          {isReview ? '批注' : '划线'}
        </span>
        <span className="text-[10.5px] text-ink-faint truncate min-w-0">《{item.book_title}》</span>
        {pct != null && <span className="ml-auto text-[10.5px] text-ink-faint">{pct}%</span>}
        <span className="text-[10.5px] text-clay opacity-0 group-hover:opacity-100 inline-flex items-center gap-0.5">
          <CornerDownLeft className="w-2.5 h-2.5" /> 插入
        </span>
      </div>
    </button>
  )
}

export default function Write() {
  const [value, setValue]   = useState(() => localStorage.getItem('writeDraft') || '')
  const [probe, setProbe]   = useState('')
  const [debounced, setDebounced] = useState('')
  const [surfaced, setSurfaced]   = useState([])
  const [loading, setLoading]     = useState(false)
  const taRef = useRef(null)

  // 草稿持久化，免得刷新丢失
  useEffect(() => { localStorage.setItem('writeDraft', value) }, [value])

  const onChange = (e) => {
    setValue(e.target.value)
    setProbe(probeText(e.target.value, e.target.selectionStart))
  }
  // 光标移动（不改字）也更新探针
  const onCaret = (e) => setProbe(probeText(value, e.target.selectionStart))

  useEffect(() => {
    const t = setTimeout(() => setDebounced(probe.length >= 6 ? probe : ''), 650)
    return () => clearTimeout(t)
  }, [probe])

  useEffect(() => {
    if (!debounced) { setSurfaced([]); return }
    setLoading(true)
    api.explore(debounced, 8)
      .then(r => setSurfaced((r.highlights || []).filter(h => (h.similarity || 0) >= 0.55)))
      .catch(() => setSurfaced([]))
      .finally(() => setLoading(false))
  }, [debounced])

  const insert = (item) => {
    const ta = taRef.current
    const pos = ta ? ta.selectionStart : value.length
    const before = value.slice(0, pos)
    const after  = value.slice(pos)
    const pad = before && !before.endsWith('\n') ? '\n' : ''
    const snippet = `${pad}\n> ${item.content}\n> —《${item.book_title}》\n\n`
    const next = before + snippet + after
    setValue(next)
    requestAnimationFrame(() => {
      if (!ta) return
      const c = (before + snippet).length
      ta.focus(); ta.setSelectionRange(c, c)
    })
  }

  const words = value.replace(/\s/g, '').length

  return (
    <div className="px-6 md:px-10 py-8">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">写作台</h1>
          <p className="text-xs text-ink-faint mt-1.5">边写边浮现你读过的相关划线与批注，点一条即插入为引用</p>
        </div>
        <span className="text-xs text-ink-faint">{words} 字</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        <textarea
          ref={taRef}
          value={value}
          onChange={onChange}
          onClick={onCaret}
          onKeyUp={onCaret}
          placeholder="开始写……写到一个想法时，右侧会浮现你过去读到的相关思考。"
          className="reading w-full min-h-[calc(100vh-220px)] text-[15px] text-ink leading-[1.9] p-5 bg-surface border border-line rounded-2xl focus:outline-none focus:ring-2 focus:ring-clay/25 resize-none"
        />

        <aside className="lg:sticky lg:top-8 self-start">
          <div className="mb-3">
            <h2 className="text-sm font-medium text-ink-soft">相关思考</h2>
            <div className="text-[11px] text-ink-faint mt-1 min-h-[16px] truncate">
              {debounced
                ? <>就「<span className="text-ink-soft">{debounced.slice(0, 16)}{debounced.length > 16 ? '…' : ''}</span>」{loading ? ' · 检索中…' : ` · ${surfaced.length} 条`}</>
                : '写到一个想法时自动浮现'}
            </div>
          </div>
          <div className="space-y-2.5 max-h-[calc(100vh-220px)] overflow-y-auto pr-0.5">
            {surfaced.map((item, i) => <SurfaceCard key={i} item={item} onInsert={insert} />)}
            {debounced && !loading && surfaced.length === 0 && (
              <p className="text-xs text-ink-faint py-3">没有相近的划线。换种说法，或继续写。</p>
            )}
            {!debounced && (
              <p className="text-xs text-ink-faint/70 py-3 leading-relaxed">
                也可以在<Link to="/explore" className="text-clay hover:text-clay-ink">探索</Link>里用概念地图漫游。
              </p>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
