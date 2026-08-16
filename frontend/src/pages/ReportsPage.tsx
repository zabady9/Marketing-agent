import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { listReports } from '../api'
import type { Report } from '../types'

const TYPE_LABEL: Record<string, string> = {
  swot: 'SWOT',
  pestel: 'PESTEL',
  feasibility: 'دراسة الجدوى',
  brand_analysis: 'تحليل الموضوع',
  market_research: 'أبحاث السوق',
}

const STATUS_CHIP: Record<string, string> = {
  ready: 'bg-green-100 text-green-700',
  generating: 'bg-yellow-100 text-yellow-700',
  failed: 'bg-red-100 text-red-700',
}

const STATUS_LABEL: Record<string, string> = {
  ready: 'جاهز',
  generating: 'جارٍ التوليد',
  failed: 'فشل',
}

export default function ReportsPage() {
  const { wsId } = useParams<{ wsId: string }>()
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!wsId) return
    listReports(wsId).then(setReports).finally(() => setLoading(false))
  }, [wsId])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">التقارير الرسمية</span>
        <Link
          to={`/workspaces/${wsId}/chat`}
          className="mr-auto text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-1.5 rounded-lg transition-colors"
        >
          + تقرير جديد
        </Link>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {loading ? (
          <div className="text-gray-400 text-sm text-center py-12">جارٍ التحميل…</div>
        ) : reports.length === 0 ? (
          <div className="text-center py-16 text-gray-400 bg-white border border-gray-200 rounded-xl">
            <p className="text-4xl mb-3">📊</p>
            <p className="text-sm mb-1">لا توجد تقارير بعد.</p>
            <p className="text-xs text-gray-400">ابدأ محادثة واطلب تحليل SWOT أو دراسة سوقية.</p>
            <Link
              to={`/workspaces/${wsId}/chat`}
              className="mt-4 inline-block text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-5 py-2 rounded-lg transition-colors"
            >
              ابدأ تحليلاً
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {reports.map(r => (
              <Link
                key={r.id}
                to={`/workspaces/${wsId}/reports/${r.id}`}
                className="flex items-center justify-between bg-white border border-gray-200 hover:border-indigo-300 hover:shadow-md rounded-xl px-6 py-4 transition-all group"
              >
                <span className="text-gray-300 group-hover:text-indigo-400 text-lg">←</span>
                <div className="flex items-center gap-4 text-right">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{TYPE_LABEL[r.analysis_type] ?? r.analysis_type}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{new Date(r.created_at).toLocaleDateString('ar-SA', { year: 'numeric', month: 'short', day: 'numeric' })}</p>
                  </div>
                  <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_CHIP[r.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
