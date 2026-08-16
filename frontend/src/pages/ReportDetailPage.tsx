import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getReport } from '../api'
import type { Report } from '../types'

const TYPE_LABEL: Record<string, string> = {
  swot: 'SWOT',
  pestel: 'PESTEL',
  feasibility: 'دراسة الجدوى',
  brand_analysis: 'تحليل الموضوع',
  market_research: 'أبحاث السوق',
}

function Section({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{title}</h3>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="text-sm text-gray-700 flex gap-2 items-start">
            <span className="text-indigo-400 mt-0.5 flex-shrink-0">·</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function KeyValue({ label, value }: { label: string; value: string | undefined }) {
  if (!value) return null
  return (
    <div className="flex gap-3 items-start">
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide w-28 flex-shrink-0 pt-0.5 text-right">{label}</span>
      <span className="text-sm text-gray-800">{value}</span>
    </div>
  )
}

function CitationList({ citations }: { citations: { title?: string; url?: string; source?: string }[] | undefined }) {
  if (!citations || citations.length === 0) return null
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-2">المصادر</h3>
      <ol className="space-y-1">
        {citations.map((c, i) => (
          <li key={i} className="text-xs text-gray-500 flex gap-1.5 items-start">
            <span className="text-gray-400 flex-shrink-0">[{i + 1}]</span>
            {c.url ? (
              <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline hover:text-indigo-800 truncate">
                {c.title || c.source || c.url}
              </a>
            ) : (
              <span>{c.title || c.source || '—'}</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

function SWOTView({ output }: { output: Record<string, unknown> }) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <div className="bg-green-50 border border-green-100 rounded-xl p-5">
        <Section title="نقاط القوة" items={output.strengths as string[]} />
      </div>
      <div className="bg-red-50 border border-red-100 rounded-xl p-5">
        <Section title="نقاط الضعف" items={output.weaknesses as string[]} />
      </div>
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-5">
        <Section title="الفرص" items={output.opportunities as string[]} />
      </div>
      <div className="bg-amber-50 border border-amber-100 rounded-xl p-5">
        <Section title="التهديدات" items={output.threats as string[]} />
      </div>
      {(output.recommendations as string[] | undefined)?.length && (
        <div className="col-span-2 bg-indigo-50 border border-indigo-100 rounded-xl p-5">
          <Section title="التوصيات" items={output.recommendations as string[]} />
        </div>
      )}
    </div>
  )
}

function PESTELView({ output }: { output: Record<string, unknown> }) {
  const sections = [
    { key: 'political', label: 'السياسية' },
    { key: 'economic', label: 'الاقتصادية' },
    { key: 'social', label: 'الاجتماعية' },
    { key: 'technological', label: 'التكنولوجية' },
    { key: 'environmental', label: 'البيئية' },
    { key: 'legal', label: 'القانونية' },
  ]
  return (
    <div className="space-y-4">
      {sections.map(s => {
        const items = output[s.key] as string[] | undefined
        if (!items?.length) return null
        return (
          <div key={s.key} className="bg-white border border-gray-200 rounded-xl p-5">
            <Section title={s.label} items={items} />
          </div>
        )
      })}
      {(output.recommendations as string[] | undefined)?.length && (
        <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-5">
          <Section title="التوصيات" items={output.recommendations as string[]} />
        </div>
      )}
    </div>
  )
}

function FeasibilityView({ output }: { output: Record<string, unknown> }) {
  const verdict = output.recommendation as string | undefined
  const verdictColor = verdict === 'proceed' ? 'bg-green-100 text-green-700' : verdict === 'do_not_proceed' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
  const verdictLabel = verdict === 'proceed' ? 'المضي قدماً' : verdict === 'do_not_proceed' ? 'عدم المضي قدماً' : 'المضي بحذر'
  return (
    <div className="space-y-4">
      {verdict && (
        <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold ${verdictColor}`}>
          {verdictLabel}
        </div>
      )}
      <KeyValue label="الملخص" value={output.summary as string} />
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <Section title="العوامل المواتية" items={output.supporting_factors as string[]} />
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <Section title="المخاطر" items={output.risks as string[]} />
        </div>
      </div>
      {(output.next_steps as string[] | undefined)?.length && (
        <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-5">
          <Section title="الخطوات التالية" items={output.next_steps as string[]} />
        </div>
      )}
    </div>
  )
}

function GenericView({ output }: { output: Record<string, unknown> }) {
  return (
    <div className="space-y-4">
      {Object.entries(output).map(([key, val]) => {
        if (!val) return null
        if (Array.isArray(val)) {
          return (
            <div key={key} className="bg-white border border-gray-200 rounded-xl p-5">
              <Section title={key.replace(/_/g, ' ')} items={val as string[]} />
            </div>
          )
        }
        if (typeof val === 'string') {
          return <KeyValue key={key} label={key.replace(/_/g, ' ')} value={val} />
        }
        return null
      })}
    </div>
  )
}

export default function ReportDetailPage() {
  const { wsId, reportId } = useParams<{ wsId: string; reportId: string }>()
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!wsId || !reportId) return
    getReport(wsId, reportId).then(setReport).finally(() => setLoading(false))
  }, [wsId, reportId])

  const output = (report?.results?.output ?? {}) as Record<string, unknown>
  const citations = report?.results?.citations as { title?: string; url?: string }[] | undefined

  function renderOutput() {
    if (!report || report.status !== 'ready') return null
    const type = report.analysis_type
    if (type === 'swot') return <SWOTView output={output} />
    if (type === 'pestel') return <PESTELView output={output} />
    if (type === 'feasibility') return <FeasibilityView output={output} />
    return <GenericView output={output} />
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}/reports`} className="text-slate-400 hover:text-white text-sm transition-colors">التقارير</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">{report ? (TYPE_LABEL[report.analysis_type] ?? report.analysis_type) : '…'}</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {loading && <div className="text-gray-400 text-sm text-center py-12">جارٍ التحميل…</div>}

        {!loading && !report && (
          <div className="text-center py-12 text-gray-400 text-sm">لم يُعثر على التقرير.</div>
        )}

        {report && (
          <div className="space-y-6">
            {/* Header card */}
            <div className="bg-white border border-gray-200 rounded-xl px-6 py-5 flex items-center justify-between">
              <div className="text-xs text-gray-400">
                {new Date(report.created_at).toLocaleDateString('ar-SA', { year: 'numeric', month: 'long', day: 'numeric' })}
              </div>
              <div className="text-right">
                <h1 className="text-lg font-bold text-gray-900">{TYPE_LABEL[report.analysis_type] ?? report.analysis_type}</h1>
                <p className="text-xs text-gray-500 mt-0.5">
                  {report.status === 'ready' ? 'جاهز' : report.status === 'generating' ? 'جارٍ التوليد…' : 'فشل التوليد'}
                </p>
              </div>
            </div>

            {/* Generating state */}
            {report.status === 'generating' && (
              <div className="text-center py-10 text-gray-400 text-sm animate-pulse">
                جارٍ توليد التقرير… أعد تحميل الصفحة بعد لحظات.
              </div>
            )}

            {/* Error state */}
            {report.status === 'failed' && (
              <div className="bg-red-50 border border-red-200 rounded-xl px-6 py-5 text-sm text-red-700 text-right">
                {report.error || 'حدث خطأ أثناء التوليد.'}
              </div>
            )}

            {/* Report content */}
            {report.status === 'ready' && renderOutput()}

            {/* Citations */}
            {report.status === 'ready' && (
              <div className="bg-white border border-gray-200 rounded-xl px-6 py-5">
                <CitationList citations={citations} />
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
