import { useState, useEffect } from 'react'
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom'
import { Sparkles, BookOpen, Search, PenLine, Settings as SettingsIcon, PanelLeftClose, PanelLeft, Power, Unplug, Loader2 } from 'lucide-react'
import { api } from './api'
import Insight from './pages/Insight'
import Books from './pages/Books'
import BookDetail from './pages/BookDetail'
import Explore from './pages/Explore'
import Write from './pages/Write'
import Settings from './pages/Settings'
import Setup from './pages/Setup'

const NAV = [
  { to: '/',        icon: Sparkles, label: '洞见' },
  { to: '/books',   icon: BookOpen, label: '书架' },
  { to: '/explore', icon: Search,   label: '探索' },
  { to: '/write',   icon: PenLine,  label: '写作' },
]

function isActive(pathname, to) {
  return to === '/' ? pathname === '/' : pathname.startsWith(to)
}

/* 桌面：左侧栏（可折叠） */
function Sidebar({ collapsed, onToggle, standalone, onQuit }) {
  const { pathname } = useLocation()
  const item = (to, Icon, label, faint = false) => {
    const active = isActive(pathname, to)
    return (
      <Link key={to} to={to} title={label}
        className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'} px-3 py-2 rounded-lg text-sm transition-colors ${
          active ? 'bg-clay-soft text-clay-ink font-medium'
                 : `${faint ? 'text-ink-faint' : 'text-ink-soft'} hover:bg-paper hover:text-ink`}`}>
        <Icon className="w-[18px] h-[18px] flex-shrink-0" strokeWidth={active ? 2.2 : 1.8} />
        {!collapsed && label}
      </Link>
    )
  }
  return (
    <aside className={`hidden md:flex fixed inset-y-0 left-0 ${collapsed ? 'w-16' : 'w-56'} bg-surface border-r border-line flex-col z-10 transition-all`}>
      <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between'} px-4 py-5`}>
        {!collapsed && (
          <div className="flex items-center gap-2">
            <span className="text-clay text-lg leading-none">❧</span>
            <div className="text-[15px] font-semibold tracking-tight text-ink">微信读书</div>
          </div>
        )}
        <button onClick={onToggle} title={collapsed ? '展开' : '收起'}
          className="text-ink-faint hover:text-ink p-1">
          {collapsed ? <PanelLeft className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </div>
      <nav className="flex-1 px-3 space-y-1">
        {NAV.map(({ to, icon: Icon, label }) => item(to, Icon, label))}
      </nav>
      <div className="px-3 py-3 border-t border-line space-y-1">
        {item('/settings', SettingsIcon, '设置', true)}
        {standalone && (
          <button onClick={onQuit} title="退出应用"
            className={`w-full flex items-center ${collapsed ? 'justify-center' : 'gap-3'} px-3 py-2 rounded-lg text-sm text-ink-faint hover:bg-rose-50 hover:text-rose-500 transition-colors`}>
            <Power className="w-[18px] h-[18px] flex-shrink-0" strokeWidth={1.8} />
            {!collapsed && '退出应用'}
          </button>
        )}
      </div>
    </aside>
  )
}

/* 移动：底部导航 */
function MobileNav() {
  const { pathname } = useLocation()
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-20 bg-surface border-t border-line flex">
      {NAV.map(({ to, icon: Icon, label }) => {
        const active = isActive(pathname, to)
        return (
          <Link key={to} to={to}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[11px] ${
              active ? 'text-clay-ink font-medium' : 'text-ink-faint'}`}>
            <Icon className="w-5 h-5" strokeWidth={active ? 2.2 : 1.8} />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}

export default function App() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('navCollapsed') === '1')
  const toggle = () => setCollapsed(v => {
    localStorage.setItem('navCollapsed', v ? '0' : '1')
    return !v
  })

  // 首启门控 + 单机版识别：apikey 路由存在(200) = 单机版 → 显示「退出应用」；
  // dev/agent 版无此路由(404) → 当作已配置、非单机，不挡、不显示退出
  const [configured, setConfigured] = useState(null)
  const [standalone, setStandalone] = useState(false)
  const [exited, setExited]   = useState(false)
  useEffect(() => {
    api.apikeyStatus()
      .then(r => { setConfigured(!!r.configured); setStandalone(true) })
      .catch(() => setConfigured(true))
  }, [])

  // 单机版：浏览器心跳。每 5s ping 一次，后端看门狗据此判活；关 tab 心跳停止，
  // 服务自动退出，防止后台进程泄漏。关闭时再用 sendBeacon 通知立即退出。
  useEffect(() => {
    if (!standalone) return
    const ping = () => api.heartbeat().catch(() => {})
    ping()
    const id = setInterval(ping, 5000)
    // 切回标签页/窗口聚焦时立即补一次心跳——后台节流期间可能漏发，回来马上重置看门狗
    const onVisible = () => { if (document.visibilityState === 'visible') ping() }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', ping)
    const onLeave = () => { try { navigator.sendBeacon('/api/shutdown') } catch {} }
    window.addEventListener('beforeunload', onLeave)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', ping)
      window.removeEventListener('beforeunload', onLeave)
    }
  }, [standalone])

  const onQuit = () => {
    if (!window.confirm('退出应用？后台服务会停止，下次双击图标重新打开。')) return
    api.shutdown().catch(() => {})   // 服务随即退出，连接会断，忽略
    setExited(true)
  }

  // 后台连不上（离开太久应用已自动关闭 / 崩溃）→ 友好提示 + 自动重连，而非生硬的 Failed to fetch
  const [disconnected, setDisconnected] = useState(false)
  useEffect(() => {
    const onDown = () => setDisconnected(true)
    window.addEventListener('weread-backend-down', onDown)
    return () => window.removeEventListener('weread-backend-down', onDown)
  }, [])
  // 断开后持续探测后台；用户重新打开应用（单实例会落回同端口）→ 探活成功 → 自动刷新恢复
  useEffect(() => {
    if (!disconnected) return
    const iv = setInterval(() => {
      fetch('/api/stats').then(r => { if (r.ok) window.location.reload() }).catch(() => {})
    }, 3000)
    return () => clearInterval(iv)
  }, [disconnected])

  if (exited) return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-6">
      <div className="text-center">
        <p className="text-lg font-medium text-ink">应用已退出</p>
        <p className="text-sm text-ink-faint mt-2">可以关闭此标签页了。下次双击「微信读书」图标重新打开。</p>
      </div>
    </div>
  )
  if (disconnected) return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-6">
      <div className="text-center max-w-xs">
        <div className="w-14 h-14 rounded-2xl bg-clay-tint flex items-center justify-center mx-auto mb-4">
          <Unplug className="w-7 h-7 text-clay" strokeWidth={1.8} />
        </div>
        <p className="text-lg font-medium text-ink">应用已休息</p>
        <p className="text-sm text-ink-soft mt-2 leading-relaxed">
          你离开太久，后台已自动关闭以省资源。<br />
          重新双击「<span className="text-ink">微信读书</span>」图标打开，这个页面会自动恢复。
        </p>
        <div className="flex items-center justify-center gap-1.5 mt-5 text-xs text-ink-faint">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> 正在等待应用重新打开…
        </div>
        <button onClick={() => window.location.reload()}
          className="mt-3 text-xs text-ink-faint hover:text-clay">手动刷新</button>
      </div>
    </div>
  )
  if (configured === null) return <div className="min-h-screen bg-paper" />
  if (!configured) return <Setup onDone={() => setConfigured(true)} />

  return (
    <div className="min-h-screen bg-paper">
      <Sidebar collapsed={collapsed} onToggle={toggle} standalone={standalone} onQuit={onQuit} />
      <MobileNav />
      <main className={`${collapsed ? 'md:ml-16' : 'md:ml-56'} pb-16 md:pb-0 transition-all`}>
        <Routes>
          <Route path="/"          element={<Insight />} />
          <Route path="/books"     element={<Books />} />
          <Route path="/books/:id" element={<BookDetail />} />
          <Route path="/explore"   element={<Explore />} />
          <Route path="/write"     element={<Write />} />
          <Route path="/settings"  element={<Settings />} />
          {/* 旧路由重定向 */}
          <Route path="/knowledge" element={<Navigate to="/explore" replace />} />
          <Route path="/echoes"    element={<Navigate to="/explore?mode=semantic" replace />} />
        </Routes>
      </main>
    </div>
  )
}
