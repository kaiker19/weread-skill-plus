import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, CheckCircle, XCircle } from 'lucide-react'
import { api } from '../api'

const FORMATS = [
  { key: 'openai',    label: 'OpenAI 兼容（DeepSeek/智谱/通义/Kimi/Ollama…）' },
  { key: 'anthropic', label: 'Anthropic（Claude）' },
]

const PLACEHOLDER = {
  openai:    'https://api.deepseek.com/v1',   // 填到 /v1 即可，后端自动补全为 chat/completions
  anthropic: 'https://api.anthropic.com/v1/messages',
}

const MODEL_PLACEHOLDER = {
  openai:    'deepseek-v4-flash',
  anthropic: 'claude-sonnet-4-5',
}

export default function Settings() {
  const [cfg, setCfg]   = useState({ endpoint: '', api_key: '', model: '', format: 'openai' })
  const [configured, setConfigured] = useState(false)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.getLlmSettings().then(s => {
      setConfigured(s.configured)
      setCfg(c => ({ ...c, endpoint: s.endpoint, model: s.model, format: s.format || 'openai' }))
    }).catch(() => {})
  }, [])

  const save = () => {
    setSaving(true); setResult(null)
    api.saveLlmSettings(cfg)
      .then(r => { setResult(r); if (r.ok) setConfigured(true) })
      .catch(e => setResult({ ok: false, error: e.message }))
      .finally(() => setSaving(false))
  }

  const field = 'w-full px-3 py-2 text-sm border border-line rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-clay/30'

  return (
    <div className="px-6 md:px-10 py-10 max-w-xl mx-auto">
      <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-ink-faint hover:text-ink mb-6">
        <ArrowLeft className="w-3.5 h-3.5" /> 返回
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">设置</h1>
      <p className="text-xs text-ink-faint mt-1.5 mb-6">
        配置一个 LLM 用于「生成读后总结」。本地保存在 <code className="text-clay">data/llm.json</code>，不上传、不进 git。
      </p>

      <h2 className="text-sm font-medium text-ink mb-3">LLM 配置</h2>
      <div className="bg-surface rounded-2xl border border-line shadow-card p-6 space-y-4">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">当前状态：</span>
          {configured
            ? <span className="text-emerald-600 flex items-center gap-1"><CheckCircle className="w-4 h-4" />已配置</span>
            : <span className="text-ink-faint">未配置</span>}
        </div>

        <div>
          <label className="block text-xs text-ink-soft mb-1">服务商格式</label>
          <select value={cfg.format} onChange={e => setCfg({ ...cfg, format: e.target.value })} className={field}>
            {FORMATS.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs text-ink-soft mb-1">Endpoint</label>
          <input className={field} placeholder={PLACEHOLDER[cfg.format]}
            value={cfg.endpoint} onChange={e => setCfg({ ...cfg, endpoint: e.target.value })} />
          {cfg.format === 'openai' && (
            <p className="text-[11px] text-ink-faint mt-1.5 leading-relaxed">
              填到 <code className="text-ink-soft">/v1</code> 即可（如 https://api.deepseek.com/v1），会自动补全。
              <br />没有 Key？国内最省事：
              <a href="https://platform.deepseek.com/sign_in" target="_blank" rel="noreferrer" className="text-clay hover:text-clay-ink">DeepSeek 获取</a>
              <span className="mx-1.5 text-line">·</span>
              <a href="https://platform.kimi.com/" target="_blank" rel="noreferrer" className="text-clay hover:text-clay-ink">Kimi 获取</a>
              <span className="ml-2 text-ink-faint/70">文档</span>
              <a href="https://api-docs.deepseek.com/zh-cn/" target="_blank" rel="noreferrer" className="text-ink-faint hover:text-clay ml-1">DeepSeek</a>
              <a href="https://platform.kimi.com/docs/api/overview" target="_blank" rel="noreferrer" className="text-ink-faint hover:text-clay ml-1.5">Kimi</a>
            </p>
          )}
        </div>

        <div>
          <label className="block text-xs text-ink-soft mb-1">模型</label>
          <input className={field} placeholder={MODEL_PLACEHOLDER[cfg.format]}
            value={cfg.model} onChange={e => setCfg({ ...cfg, model: e.target.value })} />
        </div>

        <div>
          <label className="block text-xs text-ink-soft mb-1">
            API Key {configured && <span className="text-ink-faint">（已保存，留空则不修改）</span>}
          </label>
          <input className={field} type="password" placeholder="sk-..."
            value={cfg.api_key} onChange={e => setCfg({ ...cfg, api_key: e.target.value })} />
        </div>

        <button onClick={save} disabled={saving || !cfg.endpoint || !cfg.model || (!cfg.api_key && !configured)}
          className="px-4 py-2 text-sm bg-clay-grad text-white rounded-lg shadow-sm hover:opacity-95 disabled:opacity-40 transition-opacity">
          {saving ? '保存并测试中…' : '保存并测试连接'}
        </button>

        {result && (
          <div className={`text-sm flex items-start gap-2 ${result.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
            {result.ok ? <CheckCircle className="w-4 h-4 mt-0.5" /> : <XCircle className="w-4 h-4 mt-0.5" />}
            {result.ok ? `连接成功，模型回复：${result.sample}` : `连接失败：${result.error}`}
          </div>
        )}
      </div>

      <p className="text-xs text-ink-faint mt-4 leading-relaxed">
        非 OpenAI 模型也能用——看的是接口格式，不是模型品牌。国内 DeepSeek/智谱/通义/Kimi 等都提供 OpenAI 兼容端点，选「OpenAI 兼容」、填它们各自的 endpoint 与模型名即可。
      </p>
    </div>
  )
}
