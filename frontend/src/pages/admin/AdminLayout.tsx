import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/admin', label: '📊 لوحة التحكم', end: true },
  { to: '/admin/workspaces', label: '🏢 مساحات العمل', end: false },
  { to: '/admin/plans', label: '📅 الخطط', end: false },
  { to: '/admin/posts', label: '📝 المنشورات', end: false },
  { to: '/admin/logs', label: '📋 سجلات الإجراءات', end: false },
]

export default function AdminLayout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <header className="bg-slate-950 text-white px-6 py-3 flex items-center gap-4 shrink-0">
        <a href="/" className="text-slate-400 hover:text-white text-xs transition-colors">→ العودة إلى التطبيق</a>
        <span className="text-slate-600 text-sm mr-2">· وكيل التسويق</span>
        <div className="flex items-center gap-2 mr-auto">
          <span className="font-semibold text-sm">لوحة تحكم الإدارة</span>
          <div className="w-7 h-7 bg-rose-500 rounded-md flex items-center justify-center text-xs font-bold">إ</div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav className="w-48 bg-slate-900 text-slate-300 flex flex-col gap-1 p-3 shrink-0">
          {links.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `px-3 py-2 rounded-lg text-sm transition-colors text-right ${
                  isActive ? 'bg-slate-700 text-white' : 'hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Main content */}
        <main className="flex-1 overflow-auto bg-gray-50 p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
