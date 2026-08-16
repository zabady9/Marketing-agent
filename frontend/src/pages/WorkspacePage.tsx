import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getAnalysisSubject, listReports, listChatSessions } from '../api'
import type { AnalysisSubject, Report, ChatSession } from '../types'

const REPORT_TYPE_LABEL: Record<string, string> = {
  swot: 'SWOT',
  pestel: 'PESTEL',
  feasibility: 'دراسة الجدوى',
  brand_analysis: 'تحليل الموضوع',
  market_research: 'أبحاث السوق',
}

const REPORT_STATUS_COLOR: Record<string, string> = {
  generating: 'bg-yellow-100 text-yellow-700',
  ready: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

export default function WorkspacePage() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [subject, setSubject] = useState<AnalysisSubject | null>(null)
  const [reports, setReports] = useState<Report[]>([])
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!wsId) return
    getAnalysisSubject(wsId)
      .then(s => {
        if (!s || s.setup_status === 'in_progress') {
          navigate(`/workspaces/${wsId}/setup`, { replace: true })
          return
        }
        setSubject(s)
      })
      .finally(() => setLoading(false))

    listReports(wsId).then(r => setReports(r.slice(0, 5))).catch(() => {})
    listChatSessions(wsId).then(s => setSessions(s.slice(0, 5))).catch(() => {})
  }, [wsId, navigate])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-400 text-sm">جارٍ التحميل…</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">{subject?.subject_name || 'مساحة العمل'}</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* Subject summary card */}
        {subject && (
          <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <Link
                to={`/workspaces/${wsId}/subject`}
                className="text-sm text-indigo-600 hover:text-indigo-800 font-medium"
              >
                ← عرض وتعديل
              </Link>
              <div className="text-right">
                <h2 className="font-semibold text-gray-900">{subject.subject_name || 'موضوع التحليل'}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{subject.industry || 'لم يُحدَّد القطاع'}</p>
              </div>
            </div>
            <div className="px-6 py-4">
              <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">المنافسون المتتبَّعون</dt>
                  <dd className="text-gray-900">{subject.tracked_competitors.length} منافس</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">محاور الاهتمام</dt>
                  <dd className="flex flex-wrap gap-1 mt-0.5">
                    {subject.areas_of_interest.length === 0 && <span className="text-gray-400">—</span>}
                    {subject.areas_of_interest.slice(0, 3).map(a => (
                      <span key={a} className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full">{a}</span>
                    ))}
                    {subject.areas_of_interest.length > 3 && (
                      <span className="text-xs text-gray-400">+{subject.areas_of_interest.length - 3}</span>
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          </section>
        )}

        {/* Quick-start chat */}
        <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 flex items-center justify-between">
            <Link
              to={`/workspaces/${wsId}/chat`}
              className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-2 rounded-lg transition-colors"
            >
              ← ابدأ تحليلاً
            </Link>
            <div className="text-right">
              <h2 className="font-semibold text-gray-900">محلل الأسواق الذكي</h2>
              <p className="text-xs text-gray-500 mt-0.5">اطرح أسئلة عن موضوعك، ابدأ تحليل SWOT أو PESTEL، أو استكشف السوق.</p>
            </div>
          </div>
        </section>

        {/* Recent chat sessions */}
        {sessions.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-3">
              <Link to={`/workspaces/${wsId}/chat`} className="text-xs text-indigo-600 hover:text-indigo-800">عرض الكل</Link>
              <h2 className="font-semibold text-gray-900">المحادثات الأخيرة</h2>
            </div>
            <div className="space-y-2">
              {sessions.map(s => (
                <Link
                  key={s.id}
                  to={`/workspaces/${wsId}/chat/${s.id}`}
                  className="flex items-center justify-between bg-white border border-gray-200 hover:border-indigo-300 rounded-xl px-5 py-3 transition-all group"
                >
                  <span className="text-gray-300 group-hover:text-indigo-400">←</span>
                  <div className="text-right">
                    <p className="text-sm text-gray-800">{s.title || 'محادثة بدون عنوان'}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{new Date(s.updated_at).toLocaleDateString('ar-SA')}</p>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Recent reports */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <Link to={`/workspaces/${wsId}/reports`} className="text-xs text-indigo-600 hover:text-indigo-800">عرض الكل</Link>
            <h2 className="font-semibold text-gray-900">التقارير الرسمية</h2>
          </div>
          {reports.length === 0 ? (
            <div className="text-center py-8 text-gray-400 bg-white border border-gray-200 rounded-xl">
              <p className="text-2xl mb-2">📊</p>
              <p className="text-sm">لا توجد تقارير بعد. ابدأ محادثة واطلب تحليل SWOT أو دراسة سوقية.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {reports.map(r => (
                <Link
                  key={r.id}
                  to={`/workspaces/${wsId}/reports/${r.id}`}
                  className="flex items-center justify-between bg-white border border-gray-200 hover:border-indigo-300 rounded-xl px-5 py-3 transition-all group"
                >
                  <span className="text-gray-300 group-hover:text-indigo-400">←</span>
                  <div className="flex items-center gap-3 text-right">
                    <div>
                      <p className="text-sm text-gray-800">{REPORT_TYPE_LABEL[r.analysis_type] ?? r.analysis_type}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{new Date(r.created_at).toLocaleDateString('ar-SA')}</p>
                    </div>
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${REPORT_STATUS_COLOR[r.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {r.status === 'ready' ? 'جاهز' : r.status === 'generating' ? 'جارٍ التوليد' : 'فشل'}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

      </main>
    </div>
  )
}
