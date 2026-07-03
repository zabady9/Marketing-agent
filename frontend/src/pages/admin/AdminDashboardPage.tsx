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

  if (loading) return <div className="text-gray-400 text-sm">جارٍ التحميل…</div>
  if (!stats) return <div className="text-red-500 text-sm">فشل تحميل الإحصائيات</div>

  return (
    <div>
      <h1 className="text-xl font-bold text-gray-900 mb-6">نظرة عامة</h1>

      <div className="mb-8">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">النظام</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="مساحات العمل" value={stats.workspaces} color="text-slate-800" />
          <StatCard label="سجلات الإجراءات" value={stats.action_logs} color="text-slate-800" />
        </div>
      </div>

      <div className="mb-8">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">الخطط</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="جاهز" value={stats.plans_ready} color="text-green-600" />
          <StatCard label="جارٍ التوليد" value={stats.plans_generating} color="text-yellow-600" />
          <StatCard label="فشل" value={stats.plans_failed} color="text-red-500" />
        </div>
      </div>

      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">المنشورات</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <StatCard label="في انتظار الموافقة" value={stats.posts_pending} color="text-yellow-600" />
          <StatCard label="مُعتمد" value={stats.posts_approved} color="text-green-600" />
          <StatCard label="مُجدول" value={stats.posts_scheduled} color="text-blue-600" />
          <StatCard label="منشور" value={stats.posts_published} color="text-purple-600" />
          <StatCard label="مرفوض" value={stats.posts_rejected} color="text-red-500" />
        </div>
      </div>
    </div>
  )
}
