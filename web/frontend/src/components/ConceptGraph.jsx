import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ForceGraph2D from 'react-force-graph-2d'
import { api } from '../api'

/* 概念知识图谱。按 yFiles 方法论：organic 力导向布局 + 按聚类上色 + 节点大小=重要度
   + 悬停聚焦邻居（focus+context，其余淡化）+ 边按相似度粗细 + 标签按缩放/重要度降噪。
   搜索高亮匹配节点；点节点看跨书划线。概念不全时就地触发生成。 */

// 取自 AntV 类目色板，鲜明而协调（限定 8 色，颜色=聚类信息）
const PALETTE = ['#5B8FF9', '#5AD8A6', '#945FB9', '#F6BD16', '#E8684A', '#6DC8EC', '#FF9D4D', '#269A99']
const idOf = (x) => (typeof x === 'object' ? x.id : x)

function analyze(nodes, links) {
  const parent = {}
  nodes.forEach(n => (parent[n.id] = n.id))
  const find = (x) => (parent[x] === x ? x : (parent[x] = find(parent[x])))
  const adj = {}
  nodes.forEach(n => (adj[n.id] = new Set()))
  links.forEach(l => {
    const a = idOf(l.source), b = idOf(l.target)
    if (adj[a] && adj[b]) { adj[a].add(b); adj[b].add(a) }
    const ra = find(a), rb = find(b)
    if (ra !== rb) parent[ra] = rb
  })
  const roots = {}, cluster = {}
  nodes.forEach(n => {
    const r = find(n.id)
    if (!(r in roots)) roots[r] = Object.keys(roots).length
    cluster[n.id] = roots[r]
  })
  return { adj, cluster }
}

export default function ConceptGraph({ highlightIds = new Set(), onSelect, selectedId = null }) {
  const [data, setData]       = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [hover, setHover]     = useState(null)
  const [pending, setPending] = useState({ concepts: 0 })
  const [caps, setCaps]       = useState({ llm: false })
  const [job, setJob]         = useState(null)
  const wrapRef = useRef(null)
  const fgRef   = useRef(null)
  const zoomedRef = useRef(false)
  const [size, setSize] = useState({ w: 800, h: 560 })

  useEffect(() => {
    api.graph().then(setData).finally(() => setLoading(false))
    api.capabilities().then(setCaps).catch(() => {})
    api.backfillPending().then(setPending).catch(() => {})
    const tick = () => api.backfillStatus().then(j => {
      setJob(j)
      if (!j.running) api.backfillPending().then(setPending).catch(() => {})
    }).catch(() => {})
    const iv = setInterval(tick, 2500)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => setSize({ w: el.clientWidth, h: Math.max(460, window.innerHeight - 230) })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 力学调参：适度斥力让簇有呼吸感，又不至于散到看不清
  useEffect(() => {
    const fg = fgRef.current
    if (!fg || data.nodes.length === 0) return
    fg.d3Force('charge').strength(-110).distanceMax(500)
    fg.d3Force('link').distance(46).strength(0.12)
    fg.d3ReheatSimulation && fg.d3ReheatSimulation()
  }, [data, size])

  const { adj, cluster } = useMemo(() => analyze(data.nodes, data.links), [data])

  const hasMatch = highlightIds.size > 0
  const matched = (id) => highlightIds.has(id)

  // 聚焦集合：悬停→该点+邻居；否则搜索命中→点亮命中概念；都没有→null
  const focus = useMemo(() => {
    if (hover && adj[hover]) return new Set([hover, ...adj[hover]])
    if (hasMatch) return highlightIds
    return null
  }, [hover, highlightIds, adj])

  // 搜索命中 → 推镜到命中概念；清空搜索 → 还原到初始全景视角
  const hadMatchRef = useRef(false)
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    if (highlightIds.size > 0) {
      hadMatchRef.current = true
      const t = setTimeout(() => {
        const ns = data.nodes.filter(n => highlightIds.has(n.id))
        if (!ns.length) return
        const cx = ns.reduce((a, n) => a + (n.x || 0), 0) / ns.length
        const cy = ns.reduce((a, n) => a + (n.y || 0), 0) / ns.length
        fg.centerAt(cx, cy, 500)
        if (ns.length <= 2) fg.zoom(2.4, 500)                       // 少量命中：固定适中缩放，避免单点被放巨大
        else fg.zoomToFit(500, 90, n => highlightIds.has(n.id))
      }, 150)
      return () => clearTimeout(t)
    }
    if (hadMatchRef.current) {           // 之前搜过、现在清空 → 还原
      hadMatchRef.current = false
      const ns = data.nodes
      if (ns.length) {
        const cx = ns.reduce((a, n) => a + (n.x || 0), 0) / ns.length
        const cy = ns.reduce((a, n) => a + (n.y || 0), 0) / ns.length
        fg.centerAt(cx, cy, 500)
        fg.zoom(1.7, 500)
      }
    }
  }, [highlightIds, data])

  const onNode = (n) => onSelect && onSelect(n.id)
  const genConcepts = () =>
    api.backfillStart('concepts').then(() => api.backfillStatus().then(setJob)).catch(e => alert(e.message))
  const genConceptsForce = () => {
    if (!window.confirm('重抽全部会用当前设置里的模型，覆盖已有概念。继续？')) return
    api.backfillStart('concepts', true).then(() => api.backfillStatus().then(setJob)).catch(e => alert(e.message))
  }

  return (
    <div>
      {job?.running && job.kind === 'concepts' ? (
        <div className="mb-3 text-xs text-ink-soft">抽取概念中 {job.done}/{job.total}… 完成后刷新看更完整的图谱</div>
      ) : (pending.concepts > 0 || (caps.llm && data.nodes.length > 0)) ? (
        <div className="mb-3 text-xs flex flex-wrap items-center gap-x-3 gap-y-1">
          {pending.concepts > 0 && (caps.llm ? (
            <span className="text-ink-soft">还有 {pending.concepts} 本书没抽概念，图谱还不完整。
              <button onClick={genConcepts} className="text-clay hover:text-clay-ink font-medium underline underline-offset-2 ml-1">点此一键抽取 →</button>
            </span>
          ) : (
            <Link to="/settings" className="text-clay hover:text-clay-ink">配置 AI 可生成完整图谱 · 去设置</Link>
          ))}
          {pending.concepts === 0 && caps.llm && data.nodes.length > 0 && (
            <button onClick={genConceptsForce} title="换模型后重新抽取全部概念（覆盖已有）"
              className="text-ink-faint hover:text-clay">重抽全部概念</button>
          )}
        </div>
      ) : null}

      <div ref={wrapRef} className="bg-surface rounded-2xl border border-line shadow-card overflow-hidden">
        {loading ? (
          <div className="p-10 text-sm text-ink-faint">加载中…</div>
        ) : data.nodes.length === 0 ? (
          <div className="p-10 text-sm text-ink-faint">还没有概念图谱。{caps.llm ? '点上方「生成概念图谱」。' : '去设置配置 AI 后生成。'}</div>
        ) : (
          <ForceGraph2D
            ref={fgRef}
            width={size.w} height={size.h}
            graphData={data}
            backgroundColor="#FFFFFF"
            nodeRelSize={4}
            cooldownTicks={90}
            onEngineStop={() => {
              if (!zoomedRef.current && fgRef.current) { fgRef.current.zoom(1.7, 500); zoomedRef.current = true }
            }}
            onNodeHover={(n) => setHover(n ? n.id : null)}
            onNodeClick={onNode}
            linkWidth={l => 0.4 + (l.value || 0.5) * 1.6}
            linkColor={l => {
              if (!focus) return 'rgba(150,167,194,0.22)'
              const on = focus.has(idOf(l.source)) && focus.has(idOf(l.target))
              return on ? 'rgba(27,136,238,0.45)' : 'rgba(200,205,212,0.06)'
            }}
            nodeCanvasObject={(node, ctx, scale) => {
              const r = Math.sqrt(Math.max(1, node.val)) * 3 + 2.5
              const on = focus ? focus.has(node.id) : true
              const isMatch = matched(node.id)
              const isHot = node.id === hover || selectedId === node.id
              ctx.globalAlpha = on ? 1 : 0.12
              ctx.beginPath()
              ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
              ctx.fillStyle = isMatch ? '#1B88EE' : PALETTE[(cluster[node.id] || 0) % PALETTE.length]
              ctx.fill()
              if (isHot) { ctx.lineWidth = 2 / scale; ctx.strokeStyle = '#1B88EE'; ctx.stroke() }
              // 标签：重要节点(val≥4)始终显示；其余放大/聚焦/悬停时显示。白色描边保证清晰
              const important = node.val >= 4
              if (on && (important || scale > 0.95 || isHot)) {
                const fs = Math.max(3, (isHot || important ? 13 : 11) / scale)
                ctx.font = `${fs}px -apple-system, sans-serif`
                ctx.textAlign = 'center'; ctx.textBaseline = 'top'
                const ly = node.y + r + 1.5
                ctx.lineWidth = 3 / scale
                ctx.strokeStyle = 'rgba(255,255,255,0.92)'
                ctx.strokeText(node.id, node.x, ly)
                ctx.fillStyle = isHot ? '#1670C9' : '#2B2620'
                ctx.fillText(node.id, node.x, ly)
              }
              ctx.globalAlpha = 1
            }}
          />
        )}
      </div>
    </div>
  )
}
