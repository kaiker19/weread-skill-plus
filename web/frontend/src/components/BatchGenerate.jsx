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
  const startForce = (kind) => {
    if (!window.confirm('重抽全部会用当前设置里的模型，覆盖已生成的内容。继续？')) return
    api.backfillStart(kind, true).then(() => api.backfillStatus().then(setJob)).catch(e => alert(e.message))
  }
  const stop  = () => api.backfillStop().catch(() => {})

  if (job?.running) {
    // 书架只管「读后总结」这件事
    if (job.kind === 'summaries') {
      return (
        <span className="flex items-center gap-2 text-xs text-ink-soft">
          <RefreshCw className="w-3 h-3 animate-spin text-clay" />
          生成读后总结 {job.done}/{job.total}
          <button onClick={stop} className="text-rose-500 hover:text-rose-600">停止</button>
        </span>
      )
    }
    // 别的任务（探索在抽概念）占着批量通道：明确告知，别让用户以为总结已抽完
    return (
      <span className="flex items-center gap-2 text-xs text-ink-faint">
        <RefreshCw className="w-3 h-3 animate-spin" />
        正在「探索」抽取概念（{job.done}/{job.total}）…完成后可生成读后总结
      </span>
    )
  }

  // 没配 LLM：有待生成才引导去设置；没有就不打扰
  if (!caps.llm) {
    return pending.summaries > 0 ? (
      <Link to="/settings" className="text-xs text-clay hover:text-clay-ink">
        配置 AI 可自动生成 {pending.summaries} 本读后总结 · 去设置
      </Link>
    ) : null
  }

  // 有待生成 → 只显示「生成（N）」；全部已生成 → 才显示「重抽全部」（换模型重来），二者不并存
  return pending.summaries > 0 ? (
    <button onClick={() => start('summaries')} className="text-xs text-clay hover:text-clay-ink font-medium">
      AI 生成读后总结（{pending.summaries}）
    </button>
  ) : (
    <button onClick={() => startForce('summaries')} title="换模型后重新生成全部读后总结（覆盖已有）"
      className="text-xs text-ink-faint hover:text-clay">
      重抽全部读后总结
    </button>
  )
}
