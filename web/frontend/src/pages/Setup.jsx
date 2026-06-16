import { useState, useEffect, useRef } from 'react'
import { Sparkles, ExternalLink, ShieldCheck, Loader2, Check, KeyRound, RefreshCw, ClipboardPaste } from 'lucide-react'
import { api } from '../api'

/* 首启向导（仅 standalone 版生效）：欢迎 → 填 WeRead Key → 全量同步 → 进入。
   视觉参考 weread 官网：渐变 CTA + 淡蓝图标底片 + 大半径柔光卡片。
   后端路由由 web/standalone/setup_api.py 提供；dev/agent 版无此路由，App 不会挂载本组件。 */

const KEY_URL = 'https://weread.qq.com/r/weread-skills'
const STEPS = ['welcome', 'key', 'sync', 'done']

function Dots({ step }) {
  const i = STEPS.indexOf(step)
  return (
    <div className="flex items-center gap-1.5 mb-6">
      {STEPS.map((s, k) => (
        <span key={s} className={`h-1 rounded-full transition-all ${
          k === i ? 'w-6 bg-clay' : k < i ? 'w-1.5 bg-clay/40' : 'w-1.5 bg-line'}`} />
      ))}
    </div>
  )
}

function Shell({ step, children }) {
  return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-6">
      <div className="w-full max-w-md bg-surface rounded-2xl border border-line shadow-airy p-8">
        <div className="flex items-center gap-2 mb-5">
          <span className="text-clay text-lg leading-none">❧</span>
          <span className="text-[14px] font-semibold tracking-tight text-ink">微信读书 · 个人知识库</span>
        </div>
        <Dots step={step} />
        {children}
      </div>
    </div>
  )
}

function Chip({ icon: Icon }) {
  return (
    <div className="w-12 h-12 rounded-2xl bg-clay-tint flex items-center justify-center mb-4">
      <Icon className="w-6 h-6 text-clay" strokeWidth={1.8} />
    </div>
  )
}

const btn = 'w-full py-2.5 rounded-xl bg-clay-grad text-white text-sm font-medium shadow-sm hover:opacity-95 active:opacity-90 disabled:opacity-40 transition-opacity flex items-center justify-center gap-2'

function Welcome({ onNext }) {
  return (
    <Shell step="welcome">
      <Chip icon={Sparkles} />
      <h1 className="text-xl font-semibold text-ink leading-snug">把读过的书<br />变成你的第二大脑</h1>
      <p className="text-sm text-ink-soft leading-relaxed mt-3">
        把你在微信读书的划线和想法，变成一个能搜索、能连接、能辅助写作的本地知识库。
      </p>
      <div className="flex items-start gap-2 mt-4 text-xs text-ink-faint bg-paper rounded-xl p-3">
        <ShieldCheck className="w-4 h-4 text-clay shrink-0 mt-0.5" />
        <span>数据全部保存在你这台电脑（<code className="text-ink-soft">~/.weread-skill-plus/</code>），不上传、不经过任何服务器。</span>
      </div>
      <button onClick={onNext} className={`${btn} mt-6`}>开始</button>
    </Shell>
  )
}

function KeyStep({ onNext }) {
  const [key, setKey]       = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState('')

  const submit = (val) => {
    const k = (val ?? key).trim()
    if (!k) return
    setSaving(true); setErr('')
    api.saveApikey(k)
      .then(() => onNext())
      .catch(e => setErr(e.message || '校验失败，请检查 Key'))
      .finally(() => setSaving(false))
  }

  // 读剪贴板 → 填入 → 直接验证（用户在 weread 页点过「复制 Key」后一步到位）
  const pasteAndVerify = async () => {
    try {
      const t = (await navigator.clipboard.readText()).trim()
      if (!t) { setErr('剪贴板是空的，先在网页点「复制 Key」'); return }
      setKey(t); submit(t)
    } catch {
      setErr('读取剪贴板失败，请手动粘贴到下面')
    }
  }

  return (
    <Shell step="key">
      <Chip icon={KeyRound} />
      <h1 className="text-lg font-semibold text-ink">填入微信读书 Key</h1>
      <p className="text-sm text-ink-soft leading-relaxed mt-2">
        分两步：先打开网页复制 Key，再回来粘贴验证。
      </p>

      {/* 第 1 步：打开网页（主操作，最显眼） */}
      <a href={KEY_URL} target="_blank" rel="noreferrer" className={`${btn} mt-5`}>
        <ExternalLink className="w-4 h-4" /> 第 1 步 · 打开网页获取 Key
      </a>
      <p className="text-[11px] text-ink-faint mt-2 text-center">登录后点页面上的「复制 Key」，再回到这里 ↓</p>

      {/* 第 2 步：粘贴验证（次操作） */}
      <button onClick={pasteAndVerify} disabled={saving}
        className="w-full mt-3 py-2.5 rounded-xl border border-clay/40 text-clay text-sm font-medium hover:bg-clay-tint disabled:opacity-40 flex items-center justify-center gap-2 transition-colors">
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardPaste className="w-4 h-4" />}
        {saving ? '验证中…' : '第 2 步 · 粘贴并验证'}
      </button>

      <div className="flex items-center gap-3 my-4 text-[11px] text-ink-faint">
        <span className="h-px flex-1 bg-line" />或手动粘贴<span className="h-px flex-1 bg-line" />
      </div>
      <div className="flex gap-2">
        <input
          type="text" value={key}
          onChange={e => setKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="粘贴 Key（形如 wrk-…）"
          className="flex-1 min-w-0 px-3 py-2 text-sm border border-line rounded-xl bg-surface focus:outline-none focus:ring-2 focus:ring-clay/30"
        />
        <button onClick={() => submit()} disabled={saving || !key.trim()}
          className="px-4 rounded-xl bg-clay-grad text-white text-sm font-medium shadow-sm hover:opacity-95 disabled:opacity-40 shrink-0">
          验证
        </button>
      </div>
      {err && <p className="text-xs text-red-500 mt-2">{err}</p>}
    </Shell>
  )
}

function SyncStep({ onNext }) {
  const [st, setSt]   = useState({ phase: '启动中', done: 0, total: 0, current: '', new_highlights: 0, new_reviews: 0, finished: false, error: '' })
  const [err, setErr] = useState('')
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    try { Notification.requestPermission?.() } catch {}   // 提前要权限，完成时好发通知
    api.fullSyncStart().catch(e => setErr(e.message || '无法开始同步'))
    const iv = setInterval(() => {
      api.fullSyncStatus().then(s => {
        setSt(s)
        if (s.finished) {
          clearInterval(iv)
          if (s.error) setErr(s.error)
          else {
            try {
              if (Notification.permission === 'granted')
                new Notification('同步完成', { body: '你的第二大脑已就绪，去看看洞见吧。' })
            } catch {}
            setTimeout(onNext, 700)
          }
        }
      }).catch(() => {})
    }, 1500)
    return () => clearInterval(iv)
  }, [])

  const PHASES = [
    { key: 'shelf', label: '获取书架' },
    { key: 'content', label: '同步划线' },
    { key: 'embedding', label: '建立语义索引' },
  ]
  const curIdx = Math.max(0, PHASES.findIndex(p => p.key === st.phase))
  const pct = st.total > 0 ? Math.min(100, Math.round((st.done / st.total) * 100)) : null

  return (
    <Shell step="sync">
      <Chip icon={RefreshCw} />
      <h1 className="text-lg font-semibold text-ink">正在为你建立第二大脑</h1>

      {/* 三阶段步骤 */}
      <div className="flex items-center gap-2 mt-4 mb-5">
        {PHASES.map((p, k) => (
          <div key={p.key} className="flex items-center gap-2 flex-1">
            <span className={`text-[11px] px-2 py-1 rounded-lg whitespace-nowrap ${
              k < curIdx ? 'bg-clay-tint text-clay' :
              k === curIdx ? 'bg-clay-grad text-white' : 'bg-paper text-ink-faint'}`}>
              {k < curIdx ? '✓ ' : ''}{p.label}
            </span>
            {k < PHASES.length - 1 && <span className="h-px flex-1 bg-line" />}
          </div>
        ))}
      </div>

      {/* 进度条 */}
      <div className="h-1.5 bg-paper rounded-full overflow-hidden">
        <div className={`h-full bg-clay-grad transition-all duration-500 ${pct == null ? 'animate-pulse w-1/3' : ''}`}
          style={pct != null ? { width: `${pct}%` } : undefined} />
      </div>

      {/* 实时计数 */}
      <div className="flex items-center justify-between mt-2.5 text-xs text-ink-faint">
        <span className="truncate">{st.current ? `《${st.current}》` : (st.phase === 'embedding' ? '正在向量化你的划线…' : '准备中…')}</span>
        {pct != null && <span className="shrink-0">{st.done}/{st.total} {st.phase === 'embedding' ? '条' : '本'}</span>}
      </div>
      {(st.new_highlights > 0 || st.new_reviews > 0) && (
        <p className="text-xs text-clay mt-3">
          已收集 <b>{st.new_highlights.toLocaleString()}</b> 条划线 · <b>{st.new_reviews.toLocaleString()}</b> 条批注
        </p>
      )}

      <p className="text-xs text-ink-faint mt-4">首次同步约 3–10 分钟，请保持应用打开，完成后会通知你。</p>
      {err && <p className="text-xs text-red-500 mt-3">同步出错：{err}。可关闭重开重试。</p>}
    </Shell>
  )
}

function Done({ onEnter }) {
  return (
    <Shell step="done">
      <div className="w-12 h-12 rounded-2xl bg-emerald-50 flex items-center justify-center mb-4">
        <Check className="w-6 h-6 text-emerald-600" />
      </div>
      <h1 className="text-lg font-semibold text-ink">同步完成</h1>
      <p className="text-sm text-ink-soft leading-relaxed mt-3">
        你的书架、划线和语义连接都准备好了。去「洞见」看看跨书的呼应吧。
      </p>
      <button onClick={onEnter} className={`${btn} mt-6`}>进入</button>
    </Shell>
  )
}

export default function Setup({ onDone }) {
  const [step, setStep] = useState('welcome')
  if (step === 'welcome') return <Welcome onNext={() => setStep('key')} />
  if (step === 'key')     return <KeyStep onNext={() => setStep('sync')} />
  if (step === 'sync')    return <SyncStep onNext={() => setStep('done')} />
  return <Done onEnter={onDone} />
}
