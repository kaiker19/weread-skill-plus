import { useState } from 'react'
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom'
import { Sparkles, BookOpen, Search, PenLine, Settings as SettingsIcon, PanelLeftClose, PanelLeft } from 'lucide-react'
import Insight from './pages/Insight'
import Books from './pages/Books'
import BookDetail from './pages/BookDetail'
import Explore from './pages/Explore'
import Write from './pages/Write'
import Settings from './pages/Settings'

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
function Sidebar({ collapsed, onToggle }) {
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
      <div className="px-3 py-3 border-t border-line">
        {item('/settings', SettingsIcon, '设置', true)}
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
  return (
    <div className="min-h-screen bg-paper">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
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
