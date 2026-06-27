import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/admin', label: '📊 Dashboard', end: true },
  { to: '/admin/workspaces', label: '🏢 Workspaces', end: false },
  { to: '/admin/plans', label: '📅 Plans', end: false },
  { to: '/admin/posts', label: '📝 Posts', end: false },
  { to: '/admin/logs', label: '📋 Action Logs', end: false },
]

export default function AdminLayout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <header className="bg-slate-950 text-white px-6 py-3 flex items-center gap-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-rose-500 rounded-md flex items-center justify-center text-xs font-bold">A</div>
          <span className="font-semibold text-sm">Admin Dashboard</span>
        </div>
        <span className="text-slate-600 text-sm ml-2">· Marketing Agent</span>
        <a href="/" className="ml-auto text-slate-400 hover:text-white text-xs transition-colors">← Back to app</a>
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
                `px-3 py-2 rounded-lg text-sm transition-colors ${
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
