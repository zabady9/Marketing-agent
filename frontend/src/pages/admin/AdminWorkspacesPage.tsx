import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminWorkspaces, adminDeleteWorkspace } from '../../api'

interface WS { id: string; name: string; autonomy_level: string; created_at: string }

export default function AdminWorkspacesPage() {
  const [rows, setRows] = useState<WS[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)

  useEffect(() => {
    adminWorkspaces().then(setRows).finally(() => setLoading(false))
  }, [])

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(prev => prev.size === rows.length ? new Set() : new Set(rows.map(r => r.id)))
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`حذف مساحة العمل "${name}" وجميع خططها ومنشوراتها وسجلاتها؟ لا يمكن التراجع عن هذا.`)) return
    setDeleting(id)
    try {
      await adminDeleteWorkspace(id)
      setRows(r => r.filter(w => w.id !== id))
      setSelected(prev => { const next = new Set(prev); next.delete(id); return next })
    } finally {
      setDeleting(null)
    }
  }

  async function handleBulkDelete() {
    if (!confirm(`حذف ${selected.size} مساحة عمل وجميع بياناتها؟ لا يمكن التراجع عن هذا.`)) return
    setBulkDeleting(true)
    const ids = Array.from(selected)
    await Promise.allSettled(ids.map(id => adminDeleteWorkspace(id)))
    setRows(r => r.filter(w => !ids.includes(w.id)))
    setSelected(new Set())
    setBulkDeleting(false)
  }

  if (loading) return <div className="text-gray-400 text-sm">جارٍ التحميل…</div>

  const allChecked = rows.length > 0 && selected.size === rows.length
  const someChecked = selected.size > 0 && selected.size < rows.length

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900">مساحات العمل <span className="text-gray-400 font-normal text-base">({rows.length})</span></h1>
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
              <th className="px-3 py-3 text-right">الاسم</th>
              <th className="px-3 py-3 text-right">الاستقلالية</th>
              <th className="px-3 py-3 text-right">تاريخ الإنشاء</th>
              <th className="px-3 py-3 text-right">المعرّف</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-5 py-8 text-center text-gray-400">لا توجد مساحات عمل</td></tr>
            )}
            {rows.map(ws => (
              <tr
                key={ws.id}
                className={`border-b border-gray-50 transition-colors ${selected.has(ws.id) ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}
              >
                <td className="pr-5 pl-3 py-3 w-10">
                  <input
                    type="checkbox"
                    checked={selected.has(ws.id)}
                    onChange={() => toggle(ws.id)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                  />
                </td>
                <td className="px-3 py-3 font-medium text-gray-900 text-right">
                  <Link to={`/workspaces/${ws.id}`} className="hover:text-indigo-600">{ws.name}</Link>
                </td>
                <td className="px-3 py-3 text-gray-500 text-right">{ws.autonomy_level}</td>
                <td className="px-3 py-3 text-gray-500 text-right">{new Date(ws.created_at).toLocaleString('ar-SA')}</td>
                <td className="px-3 py-3 text-gray-400 font-mono text-xs text-right">{ws.id}</td>
                <td className="px-5 py-3 text-left">
                  <button
                    onClick={() => handleDelete(ws.id, ws.name)}
                    disabled={deleting === ws.id}
                    className="text-xs text-red-500 hover:text-red-700 disabled:opacity-50 transition-colors"
                  >
                    {deleting === ws.id ? 'جارٍ الحذف…' : 'حذف'}
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
