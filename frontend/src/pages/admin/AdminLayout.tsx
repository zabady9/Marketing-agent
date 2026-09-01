import { Link, NavLink, Outlet } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/admin/projects', label: 'Projects' },
  { to: '/admin/studies', label: 'Studies' },
  { to: '/admin/chat-sessions', label: 'Chat Sessions' },
  { to: '/admin/memory', label: 'Memory' },
  { to: '/admin/glossary', label: 'Glossary' },
]

// Root layout for the /admin section — sidebar nav + a permanent warning
// banner (this panel has no auth and writes bypass application logic) +
// an outlet for the current entity page.
export function AdminLayout() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="border-b border-yellow-300 bg-yellow-50 px-4 py-2 text-center text-sm font-medium text-yellow-800">
        This is a raw data admin panel with no access control — changes bypass application logic.
      </div>
      <div className="flex">
        <aside className="w-56 shrink-0 border-r border-gray-200 bg-white px-3 py-6">
          <p className="px-2 pb-4 text-lg font-semibold text-gray-900">Admin</p>
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `block rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-8 border-t border-gray-200 pt-4">
            <Link to="/" className="px-2 text-sm text-gray-500 hover:text-gray-700">
              ← Back to app
            </Link>
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
