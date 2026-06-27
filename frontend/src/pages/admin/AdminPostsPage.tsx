import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminPosts, adminDeletePost, type AdminPost } from '../../api'

const STATUS_COLOR: Record<string, string> = {
  pending_approval: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  scheduled: 'bg-blue-100 text-blue-700',
  published: 'bg-purple-100 text-purple-700',
  rejected: 'bg-red-100 text-red-700',
  draft: 'bg-gray-100 text-gray-600',
}

export default function AdminPostsPage() {
  const [rows, setRows] = useState<AdminPost[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)

  function load(status: string) {
    setLoading(true)
    setSelected(new Set())
    adminPosts(status === 'all' ? undefined : status)
      .then(setRows)
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(filter) }, [filter])

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    const allSelected = rows.length > 0 && rows.every(r => selected.has(r.id))
    setSelected(allSelected ? new Set() : new Set(rows.map(r => r.id)))
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this post?')) return
    setDeleting(id)
    try {
      await adminDeletePost(id)
      setRows(r => r.filter(p => p.id !== id))
      setSelected(prev => { const next = new Set(prev); next.delete(id); return next })
    } finally {
      setDeleting(null)
    }
  }

  async function handleBulkDelete() {
    if (!confirm(`Delete ${selected.size} post(s)?`)) return
    setBulkDeleting(true)
    const ids = Array.from(selected)
    await Promise.allSettled(ids.map(id => adminDeletePost(id)))
    setRows(r => r.filter(p => !ids.includes(p.id)))
    setSelected(new Set())
    setBulkDeleting(false)
  }

  const allChecked = rows.length > 0 && rows.every(r => selected.has(r.id))
  const someChecked = rows.some(r => selected.has(r.id)) && !allChecked

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900">Posts <span className="text-gray-400 font-normal text-base">({rows.length})</span></h1>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <button
              onClick={handleBulkDelete}
              disabled={bulkDeleting}
              className="bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              {bulkDeleting ? 'Deleting…' : `Delete ${selected.size} selected`}
            </button>
          )}
          <select value={filter} onChange={e => setFilter(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option value="all">All statuses</option>
            <option value="pending_approval">Pending Approval</option>
            <option value="approved">Approved</option>
            <option value="scheduled">Scheduled</option>
            <option value="published">Published</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <th className="pl-5 pr-3 py-3 w-10">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    ref={el => { if (el) el.indeterminate = someChecked }}
                    onChange={toggleAll}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                  />
                </th>
                <th className="px-3 py-3 text-left">Workspace</th>
                <th className="px-3 py-3 text-left">Day / Theme</th>
                <th className="px-3 py-3 text-left">Status</th>
                <th className="px-3 py-3 text-left">Postiz ID</th>
                <th className="px-3 py-3 text-left">Created</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-gray-400">No posts</td></tr>
              )}
              {rows.map(post => (
                <>
                  <tr
                    key={post.id}
                    className={`border-b border-gray-50 cursor-pointer transition-colors ${selected.has(post.id) ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}
                    onClick={() => setExpanded(expanded === post.id ? null : post.id)}
                  >
                    <td className="pl-5 pr-3 py-3 w-10" onClick={e => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(post.id)}
                        onChange={() => toggle(post.id)}
                        className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                      />
                    </td>
                    <td className="px-3 py-3 text-gray-700">
                      <Link
                        to={`/workspaces/${post.workspace_id}/plans/${post.plan_id}`}
                        onClick={e => e.stopPropagation()}
                        className="hover:text-indigo-600 font-medium"
                      >
                        {post.workspace_name}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-medium text-gray-800">Day {post.day}</span>
                      <span className="text-gray-400 mx-1">·</span>
                      <span className="text-gray-500">{post.theme}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[post.status] ?? STATUS_COLOR.draft}`}>
                        {post.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-gray-400">{post.postiz_post_id || '—'}</td>
                    <td className="px-3 py-3 text-gray-400 text-xs">{new Date(post.created_at).toLocaleString()}</td>
                    <td className="px-5 py-3 text-right" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => handleDelete(post.id)}
                        disabled={deleting === post.id}
                        className="text-xs text-red-500 hover:text-red-700 disabled:opacity-50 transition-colors"
                      >
                        {deleting === post.id ? 'Deleting…' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                  {expanded === post.id && (
                    <tr key={`${post.id}-expanded`} className="bg-indigo-50 border-b border-indigo-100">
                      <td colSpan={7} className="px-5 py-4">
                        <p className="text-xs font-medium text-indigo-600 mb-1">{post.format} · {post.angle} · {post.suggested_time}</p>
                        <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed mb-2">{post.content}</p>
                        {post.hashtags.length > 0 && <p className="text-sm text-indigo-500">{post.hashtags.join(' ')}</p>}
                        <p className="text-xs text-gray-400 mt-2 font-mono">{post.id}</p>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
