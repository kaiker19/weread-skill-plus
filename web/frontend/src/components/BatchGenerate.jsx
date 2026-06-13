import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { api } from '../api'

/* 书架「X 本」同一行的轻提示：只做「读后总结」这一件价值即时可见的事。
   概念抽取是知识图谱的内部步骤，不在书架暴露（等图谱页就地触发）。 */
export default function BatchGenerate() {
  const [caps, setCaps]       = useState({ llm: false })
  const [pending, setPending] = useState({ summaries: 0, concepts: 0 })
  const [job, setJob]         = useState(null)
  const pollRef = useRef(null)

  const refresh = () => api.backfillPending().then(setPending).catch(() => {})

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => {})
    refresh()
    const tick = () => api.backfillStatus().then(j => { setJob(j); if (!j.running) refresh() }).catch(() => {})
    tick()
    pollRef.current = setInterval(tick, 2000)
    return () => clearInterval(pollRef.current)
  }, [])

  const start = (kind) => api.backfillStart(kind).then(() => api.backfillStatus().then(setJob)).catch(e => alert(e.message))
  const stop  = () => api.backfillStop().catch(() => {})

  if (job?.running) {
    return (
      <span className="flex items-center gap-2 text-xs text-ink-soft">
        <RefreshCw className="w-3 h-3 animate-spin text-clay" />
        {job.kind === 'concepts' ? '抽取概念' : '生成总结'} {job.done}/{job.total}
        <button onClick={stop} className="text-rose-500 hover:text-rose-600">停止</button>
      </span>
    )
  }

  if (pending.summaries === 0) return null

  // 没配 LLM：不展示生成按钮，而是引导去设置
  if (!caps.llm) {
    return (
      <Link to="/settings" className="text-xs text-clay hover:text-clay-ink">
        配置 AI 可自动生成 {pending.summaries} 本读后总结 · 去设置
      </Link>
    )
  }

  return (
    <button onClick={() => start('summaries')} className="text-xs text-clay hover:text-clay-ink font-medium">
      生成读后总结（{pending.summaries}）
    </button>
  )
}
