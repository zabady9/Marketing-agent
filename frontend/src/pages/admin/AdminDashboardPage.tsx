import { useEffect, useState } from 'react'
import { adminStats, type AdminStats } from '../../api'

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
    </div>
  )
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    adminStats().then(setStats).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-gray-400 text-sm">Loading…</div>
  if (!stats) return <div className="text-red-500 text-sm">Failed to load stats</div>

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-900 mb-6">Overview</h1>

      <div className="mb-8">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">System</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="Workspaces" value={stats.workspaces} color="text-slate-800" />
          <StatCard label="Action Logs" value={stats.action_logs} color="text-slate-800" />
        </div>
      </div>

      <div className="mb-8">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Plans</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="Ready" value={stats.plans_ready} color="text-green-600" />
          <StatCard label="Generating" value={stats.plans_generating} color="text-yellow-600" />
          <StatCard label="Failed" value={stats.plans_failed} color="text-red-500" />
        </div>
      </div>

      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Posts</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="Pending Approval" value={stats.posts_pending} color="text-yellow-600" />
          <StatCard label="Approved" value={stats.posts_approved} color="text-green-600" />
          <StatCard label="Scheduled" value={stats.posts_scheduled} color="text-blue-600" />
          <StatCard label="Published" value={stats.posts_published} color="text-purple-600" />
          <StatCard label="Rejected" value={stats.posts_rejected} color="text-red-500" />
        </div>
      </div>
    </div>
  )
}
