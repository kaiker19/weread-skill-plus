import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Search, Bookmark, MessageSquare } from 'lucide-react'
import { api, fmtDate } from '../api'
import ConceptGraph from '../components/ConceptGraph'

/* 探索 = 可搜索的知识地图（P1）：一个搜索框，既点亮图谱里相关概念，
   又在右栏列出语义相近的划线。关键词/语义/图谱三个模式合而为一。 */

function PassageCard({ item }) {
  const isReview = item.source_type === 'review'
  const simPct = item.similarity != null ? Math.round(item.similarity * 100) : null
  return (
    <div className="bg-surface rounded-xl border border-line shadow-card px-4 py-3">
      <p className="reading text-[13.5px] text-ink leading-[1.8]">{item.content}</p>
      <div className="flex flex-wrap items-center gap-2 mt-2">
        <span className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded ${
          isReview ? 'bg-amber-50 text-amber-600' : 'bg-clay-soft text-clay-ink'}`}>
          {isReview ? <MessageSquare className="w-2.5 h-2.5" /> : <Bookmark className="w-2.5 h-2.5" />}
          {isReview ? '批注' : '划线'}
        </span>
        {item.book_id
          ? <Link to={`/books/${item.book_id}`} className="text-[11px] text-ink-faint hover:text-clay truncate">《{item.book_title}》</Link>
          : <span className="text-[11px] text-ink-faint truncate">《{item.book_title}》</span>}
        {simPct != null && <span className="ml-auto text-[11px] text-ink-faint">{simPct}%</span>}
        {item.create_time && <span className="text-[11px] text-ink-faint">{fmtDate(item.create_time)}</span>}
      </div>
    </div>
  )
}

export default function Explore() {
  const [q, setQ]                 = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [passages, setPassages]   = useState([])
  const [matchedIds, setMatchedIds] = useState(new Set())
  const [loading, setLoading]     = useState(false)
  const [concept, setConcept]     = useState(null)   // 点击图谱节点 → {tag, highlights}

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 450)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    if (!debouncedQ) { setPassages([]); setMatchedIds(new Set()); return }
    setConcept(null)                                  // 新搜索 → 收起已点开的概念
    setLoading(true)
    api.explore(debouncedQ)
      .then(r => { setPassages(r.highlights || []); setMatchedIds(new Set(r.concepts || [])) })
      .catch(() => { setPassages([]); setMatchedIds(new Set()) })
      .finally(() => setLoading(false))
  }, [debouncedQ])

  const onSelectConcept = (tag) =>
    api.graphConcept(tag).then(hl => setConcept({ tag, highlights: hl })).catch(() => {})

  const hasQ = debouncedQ.length > 0
  const showPanel = !!concept || hasQ

  return (
    <div className="px-6 md:px-10 py-8">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">探索</h1>
        <p className="text-xs text-ink-faint mt-1.5">在概念地图里漫游；搜索会点亮相关概念，并列出语义相近的划线</p>
      </div>

      <div className="relative max-w-xl mb-5">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
        <input
          type="text"
          placeholder="输入概念或一段想法，找回并连接你的思考…"
          value={q}
          onChange={e => setQ(e.target.value)}
          className="w-full pl-9 pr-4 py-2 text-sm border border-line rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-clay/30"
        />
      </div>

      {/* 图谱全宽；详情走右侧统一浮层（不占布局、不抖动） */}
      <ConceptGraph highlightIds={matchedIds} onSelect={onSelectConcept} selectedId={concept?.tag} />

      {showPanel && (
        <aside className="fixed right-0 top-0 bottom-0 w-80 max-w-[85vw] bg-surface border-l border-line z-30 p-5 overflow-y-auto shadow-2xl">
          {concept ? (
            <>
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-base font-semibold text-ink">{concept.tag}</h3>
                <button onClick={() => setConcept(null)} className="text-ink-faint hover:text-ink text-sm">关闭</button>
              </div>
              <p className="text-xs text-ink-faint mb-4">{concept.highlights.length} 条相关划线</p>
              <div className="space-y-4">
                {concept.highlights.map((h, i) => (
                  <div key={i}>
                    <p className="reading text-[13.5px] text-ink leading-relaxed">{h.content}</p>
                    <Link to={`/books/${h.book_id}`} className="text-xs text-ink-faint hover:text-clay">《{h.book_title}》</Link>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="text-xs text-ink-faint mb-3">
                「{debouncedQ}」相关划线 {loading ? '…' : `· ${passages.length} 条`}
              </div>
              <div className="space-y-2.5">
                {passages.map((p, i) => <PassageCard key={i} item={p} />)}
                {!loading && passages.length === 0 && <p className="text-xs text-ink-faint py-4">没有相近的划线</p>}
              </div>
            </>
          )}
        </aside>
      )}
    </div>
  )
}
