import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Bookmark, MessageSquare, Sparkles, RefreshCw, Pencil } from 'lucide-react'
import { api, fmtDate } from '../api'

function groupByChapter(highlights) {
  const groups = {}
  for (const h of highlights) {
    const ch = h.chapter_title || '未分章节'
    if (!groups[ch]) groups[ch] = []
    groups[ch].push(h)
  }
  return groups
}

/* 极简 markdown 渲染：**加粗**、> 引用、段落。不引依赖，够总结用。 */
function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} className="text-ink">{p.slice(2, -2)}</strong>
      : p
  )
}

function SummaryBody({ text }) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div className="reading text-[15px] text-ink leading-[1.9] space-y-3">
      {blocks.map((b, i) => {
        if (b.startsWith('>')) {
          return (
            <blockquote key={i} className="border-l-2 border-clay/40 pl-4 text-ink-soft italic">
              {renderInline(b.replace(/^>\s?/gm, ''))}
            </blockquote>
          )
        }
        return <p key={i}>{renderInline(b)}</p>
      })}
    </div>
  )
}

/* 速览：有总结优先显示总结；否则显示提取式代表划线。
   支持手写/编辑总结，覆盖自动生成的内容。 */
function DigestCard({ summary, representative, reviewCount, canGenerate, onGenerate, generating, onSave }) {
  const hasSummary = !!summary
  const [editing, setEditing] = useState(false)
  const [draft, setDraft]     = useState('')
  const [saving, setSaving]   = useState(false)

  const startEdit = () => { setDraft(summary || ''); setEditing(true) }
  const save = () => {
    const t = draft.trim()
    if (!t) return
    setSaving(true)
    Promise.resolve(onSave(t)).then(() => setEditing(false)).finally(() => setSaving(false))
  }

  return (
    <div className="bg-surface rounded-2xl border border-line shadow-card p-6 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-clay-ink flex items-center gap-1.5">
          <Sparkles className="w-4 h-4" /> {hasSummary ? '读后总结' : '速览'}
        </h2>
        {!editing && (
          <div className="flex items-center gap-3">
            <button onClick={startEdit}
              className="flex items-center gap-1 text-xs text-ink-faint hover:text-clay">
              <Pencil className="w-3 h-3" /> {hasSummary ? '编辑' : '手写总结'}
            </button>
            {canGenerate ? (
              <button onClick={onGenerate} disabled={generating}
                className="flex items-center gap-1 text-xs text-ink-faint hover:text-clay disabled:opacity-40">
                <RefreshCw className={`w-3 h-3 ${generating ? 'animate-spin' : ''}`} />
                {generating ? '生成中…' : hasSummary ? 'AI 重新生成' : 'AI 生成总结'}
              </button>
            ) : !hasSummary && (
              <Link to="/settings" className="text-xs text-ink-faint hover:text-clay">
                未配置 LLM · 去设置
              </Link>
            )}
          </div>
        )}
      </div>
      {editing ? (
        <div>
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            rows={12}
            autoFocus
            placeholder="写下你的读后总结，覆盖自动生成的内容…支持 **加粗** 与 > 引用"
            className="reading w-full text-[14px] text-ink leading-[1.8] p-3 border border-line rounded-lg bg-paper focus:outline-none focus:ring-2 focus:ring-clay/30 resize-y"
          />
          <div className="flex items-center gap-2 mt-2">
            <button onClick={save} disabled={saving || !draft.trim()}
              className="text-xs px-3 py-1.5 rounded-lg bg-clay-grad text-white shadow-sm hover:opacity-95 disabled:opacity-40">
              {saving ? '保存中…' : '保存'}
            </button>
            <button onClick={() => setEditing(false)}
              className="text-xs px-3 py-1.5 rounded-lg text-ink-faint hover:text-ink">取消</button>
            <span className="text-[11px] text-ink-faint ml-auto">手写内容会覆盖自动生成</span>
          </div>
        </div>
      ) : hasSummary ? (
        <SummaryBody text={summary} />
      ) : representative.length > 0 ? (
        <div className="space-y-2.5">
          <p className="text-xs text-ink-faint">代表性划线（按全书语义中心选取）</p>
          {representative.map((h, i) => (
            <p key={i} className="reading text-[14px] text-ink leading-[1.8] pl-3 border-l-2 border-clay/30">
              {h.content}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-sm text-ink-faint">暂无可速览的内容。</p>
      )}
    </div>
  )
}

export default function BookDetail() {
  const { id }           = useParams()
  const [data, setData]  = useState(null)
  const [tab, setTab]    = useState('highlights')
  const [loading, setLoading] = useState(true)
  const [caps, setCaps]  = useState({ llm: false })
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.book(id).then(setData).finally(() => setLoading(false))
    api.capabilities().then(setCaps).catch(() => {})
  }, [id])

  const onGenerate = () => {
    setGenerating(true)
    api.summarizeBook(id, !!data?.summary)
      .then(r => setData(d => ({ ...d, summary: r.summary })))
      .catch(e => alert('生成失败：' + e.message))
      .finally(() => setGenerating(false))
  }

  const onSaveSummary = (text) =>
    api.saveBookSummary(id, text)
      .then(r => setData(d => ({ ...d, summary: r.summary })))
      .catch(e => { alert('保存失败：' + e.message); throw e })

  if (loading) return <div className="p-10 text-sm text-ink-faint">加载中…</div>
  if (!data)   return <div className="p-10 text-sm text-ink-faint">未找到该书籍</div>

  const { book, highlights, reviews, summary } = data
  const representative = data.digest?.representative || []
  const chapterGroups = groupByChapter(highlights)

  return (
    <div className="px-6 md:px-10 py-10 max-w-3xl mx-auto">
      <Link to="/books" className="inline-flex items-center gap-1.5 text-xs text-ink-faint hover:text-ink mb-6">
        <ArrowLeft className="w-3.5 h-3.5" /> 返回书架
      </Link>

      {/* Book header — 封面 + 信息 */}
      <div className="bg-surface rounded-2xl border border-line shadow-card p-6 mb-6 flex gap-5">
        {book.cover ? (
          <img src={book.cover} alt={book.title}
            className="w-[72px] h-[102px] object-cover rounded-md border border-line flex-shrink-0" />
        ) : null}
        <div className="min-w-0">
          <h1 className="reading text-xl font-semibold text-ink leading-snug">{book.title}</h1>
          <p className="text-sm text-ink-soft mt-1.5">{book.author}</p>
          <div className="flex flex-wrap items-center gap-3 mt-4 text-xs text-ink-faint">
            {book.category && <span className="bg-paper border border-line px-2 py-0.5 rounded">{book.category}</span>}
            {book.finish_time
              ? <span className="text-emerald-600">读完于 {fmtDate(book.finish_time)}</span>
              : highlights.length > 0
              ? <span className="text-clay">在读</span>
              : <span>未开始</span>
            }
            <span>{highlights.length} 划线</span>
            <span>{reviews.length} 批注</span>
          </div>
        </div>
      </div>

      {/* 速览：总结优先，否则提取式代表划线 */}
      <DigestCard
        summary={summary}
        representative={representative}
        reviewCount={reviews.length}
        canGenerate={caps.llm}
        onGenerate={onGenerate}
        generating={generating}
        onSave={onSaveSummary}
      />

      {/* Tabs */}
      <div className="flex gap-1 bg-paper border border-line p-0.5 rounded-lg w-fit mb-6">
        {[
          { key: 'highlights', label: `划线 ${highlights.length}`, icon: Bookmark },
          { key: 'reviews',    label: `批注 ${reviews.length}`,    icon: MessageSquare },
        ].map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-1.5 text-xs rounded-md transition-colors ${
              tab === key ? 'bg-surface text-ink shadow-sm font-medium' : 'text-ink-soft hover:text-ink'
            }`}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {/* Highlights by chapter */}
      {tab === 'highlights' && (
        highlights.length > 0 ? (
          <div className="space-y-7">
            {Object.entries(chapterGroups).map(([chapter, items]) => (
              <div key={chapter}>
                <h3 className="text-xs font-medium text-clay/80 tracking-wide mb-3">{chapter}</h3>
                <div className="space-y-3">
                  {items.map(h => (
                    <div key={h.highlight_id}
                      className="bg-surface rounded-xl border border-line shadow-card border-l-[3px] border-l-clay/40 px-5 py-4">
                      <p className="reading text-[15px] text-ink leading-[1.85]">{h.content}</p>
                      {h.create_time && (
                        <p className="text-xs text-ink-faint mt-2.5">{fmtDate(h.create_time)}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-sm text-ink-faint">暂无划线</div>
        )
      )}

      {/* Reviews */}
      {tab === 'reviews' && (
        reviews.length > 0 ? (
          <div className="space-y-4">
            {reviews.map(r => (
              <div key={r.review_id} className="bg-surface rounded-xl border border-line shadow-card px-5 py-4">
                {r.abstract && (
                  <p className="reading text-[13px] text-ink-soft leading-[1.7] border-l-2 border-clay/30 pl-3 mb-2.5">
                    {r.abstract}
                  </p>
                )}
                <p className="reading text-[15px] text-ink leading-[1.85]">{r.content}</p>
                {r.create_time && (
                  <p className="text-xs text-ink-faint mt-3">{fmtDate(r.create_time)}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-sm text-ink-faint">暂无批注</div>
        )
      )}
    </div>
  )
}
