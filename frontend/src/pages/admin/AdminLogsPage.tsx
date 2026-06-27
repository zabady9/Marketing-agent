import { useEffect, useState } from 'react'
import { adminLogs, type AdminLog } from '../../api'

const ACTION_COLOR: Record<string, string> = {
  approve_post: 'text-green-600',
  reject_post: 'text-red-500',
  schedule_post: 'text-blue-600',
  edit_post: 'text-orange-500',
  regenerate_post: 'text-violet-600',
  create_workspace: 'text-slate-600',
  upsert_brand_profile: 'text-indigo-600',
  generate_plan: 'text-yellow-600',
}

export default function AdminLogsPage() {
  const [logs, setLogs] = useState<AdminLog[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const limit = 50

  function load(o: number) {
    setLoading(true)
    adminLogs(limit, o)
      .then(data => {
        setLogs(prev => o === 0 ? data : [...prev, ...data])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(0) }, [])

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-900 mb-6">Action Logs</h1>

      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <th className="px-5 py-3 text-left">Time</th>
              <th className="px-5 py-3 text-left">Action</th>
              <th className="px-5 py-3 text-left">Actor</th>
              <th className="px-5 py-3 text-left">Workspace</th>
              <th className="px-5 py-3 text-left">Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 && !loading && (
              <tr><td colSpan={5} className="px-5 py-8 text-center text-gray-400">No logs yet</td></tr>
            )}
            {logs.map(log => (
              <>
                <tr
                  key={log.id}
                  className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                >
                  <td className="px-5 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-2.5">
                    <span className={`font-mono text-xs font-medium ${ACTION_COLOR[log.action] ?? 'text-gray-700'}`}>
                      {log.action}
                    </span>
                  </td>
                  <td className="px-5 py-2.5 text-gray-500 text-xs">{log.actor}</td>
                  <td className="px-5 py-2.5 text-gray-400 font-mono text-xs">{log.workspace_id.slice(0, 8)}…</td>
                  <td className="px-5 py-2.5 text-gray-400 text-xs">
                    {Object.keys(log.payload).slice(0, 2).map(k => `${k}: ${String(log.payload[k]).slice(0, 20)}`).join(' · ')}
                  </td>
                </tr>
                {expanded === log.id && (
                  <tr key={`${log.id}-exp`} className="bg-slate-50 border-b border-slate-100">
                    <td colSpan={5} className="px-5 py-3">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-xs font-semibold text-gray-500 mb-1">Payload</p>
                          <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 overflow-auto max-h-40">
                            {JSON.stringify(log.payload, null, 2)}
                          </pre>
                        </div>
                        {log.result && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 mb-1">Result</p>
                            <pre className="text-xs text-gray-700 bg-white border border-gray-200 rounded p-2 overflow-auto max-h-40">
                              {JSON.stringify(log.result, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>

        {loading && <div className="px-5 py-4 text-center text-gray-400 text-sm">Loading…</div>}

        {!loading && logs.length >= limit && (
          <div className="px-5 py-4 border-t border-gray-100 text-center">
            <button
              onClick={() => { const next = offset + limit; setOffset(next); load(next) }}
              className="text-sm text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
            >
              Load more
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
