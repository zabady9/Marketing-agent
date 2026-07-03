import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminPlans, adminDeletePlan, type AdminPlan } from '../../api'

const STATUS_COLOR: Record<string, string> = {
  generating: 'bg-yellow-100 text-yellow-700',
  ready: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

const STATUS_LABEL: Record<string, string> = {
  generating: 'جارٍ التوليد',
  ready: 'جاهز',
  failed: 'فشل',
}

export default function AdminPlansPage() {
  const [rows, setRows] = useState<AdminPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)

  useEffect(() => {
    adminPlans().then(setRows).finally(() => setLoading(false))
  }, [])

  const filtered = filter === 'all' ? rows : rows.filter(r => r.status === filter)

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    const visibleIds = filtered.map(r => r.id)
    const allSelected = visibleIds.every(id => selected.has(id))
    setSelected(prev => {
      const next = new Set(prev)
      if (allSelected) visibleIds.forEach(id => next.delete(id))
      else visibleIds.forEach(id => next.add(id))
      return next
    })
  }

  async function handleDelete(id: string) {
    if (!confirm('حذف هذه الخطة وجميع منشوراتها؟')) return
    setDeleting(id)
    try {
      await adminDeletePlan(id)
      setRows(r => r.filter(p => p.id !== id))
      setSelected(prev => { const next = new Set(prev); next.delete(id); return next })
    } finally {
      setDeleting(null)
    }
  }

  async function handleBulkDelete() {
    if (!confirm(`حذف ${selected.size} خطة وجميع منشوراتها؟`)) return
    setBulkDeleting(true)
    const ids = Array.from(selected)
    await Promise.allSettled(ids.map(id => adminDeletePlan(id)))
    setRows(r => r.filter(p => !ids.includes(p.id)))
    setSelected(new Set())
    setBulkDeleting(false)
  }

  if (loading) return <div className="text-gray-400 text-sm">جارٍ التحميل…</div>

  const visibleIds = filtered.map(r => r.id)
  const allChecked = visibleIds.length > 0 && visibleIds.every(id => selected.has(id))
  const someChecked = visibleIds.some(id => selected.has(id)) && !allChecked

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <select value={filter} onChange={e => setFilter(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option value="all">جميع الحالات</option>
            <option value="generating">جارٍ التوليد</option>
            <option value="ready">جاهز</option>
            <option value="failed">فشل</option>
          </select>
          {selected.size > 0 && (
            <button
              onClick={handleBulkDelete}
              disabled={bulkDeleting}
              className="bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              {bulkDeleting ? 'جارٍ الحذف…' : `حذف ${selected.size} مختار`}
            </button>
          )}
        </div>
        <h1 className="text-xl font-bold text-gray-900">الخطط <span className="text-gray-400 font-normal text-base">({filtered.length})</span></h1>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <th className="pr-5 pl-3 py-3 w-10">
                <input
                  type="checkbox"
                  checked={allChecked}
                  ref={el => { if (el) el.indeterminate = someChecked }}
                  onChange={toggleAll}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
              </th>
              <th className="px-3 py-3 text-right">مساحة العمل</th>
              <th className="px-3 py-3 text-right">الهدف</th>
              <th className="px-3 py-3 text-right">الحالة</th>
              <th className="px-3 py-3 text-right">المنشورات</th>
              <th className="px-3 py-3 text-right">تاريخ الإنشاء</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-5 py-8 text-center text-gray-400">لا توجد خطط</td></tr>
            )}
            {filtered.map(plan => (
              <tr key={plan.id} className={`border-b border-gray-50 transition-colors ${selected.has(plan.id) ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}>
                <td className="pr-5 pl-3 py-3 w-10">
                  <input
                    type="checkbox"
                    checked={selected.has(plan.id)}
                    onChange={() => toggle(plan.id)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                  />
                </td>
                <td className="px-3 py-3 text-gray-700 text-right">
                  <Link to={`/workspaces/${plan.workspace_id}`} className="hover:text-indigo-600 font-medium">{plan.workspace_name}</Link>
                </td>
                <td className="px-3 py-3 text-gray-600 max-w-xs truncate text-right">
                  <Link to={`/workspaces/${plan.workspace_id}/plans/${plan.id}`} className="hover:text-indigo-600">
                    {plan.goal || <span className="italic text-gray-400">وعي عام</span>}
                  </Link>
                </td>
                <td className="px-3 py-3 text-right">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[plan.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[plan.status] ?? plan.status}
                  </span>
                  {plan.error && <p className="text-xs text-red-500 mt-0.5 truncate max-w-xs">{plan.error}</p>}
                </td>
                <td className="px-3 py-3 text-gray-500 text-right">{plan.post_count}</td>
                <td className="px-3 py-3 text-gray-400 text-xs text-right">{new Date(plan.created_at).toLocaleString('ar-SA')}</td>
                <td className="px-5 py-3 text-left">
                  <button
                    onClick={() => handleDelete(plan.id)}
                    disabled={deleting === plan.id}
                    className="text-xs text-red-500 hover:text-red-700 disabled:opacity-50 transition-colors"
                  >
                    {deleting === plan.id ? 'جارٍ الحذف…' : 'حذف'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
