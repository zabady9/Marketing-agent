import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getBrandProfile, listPlans, generatePlan } from '../api'
import type { BrandProfile, Plan } from '../types'

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

export default function WorkspacePage() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [brand, setBrand] = useState<BrandProfile | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loadingBrand, setLoadingBrand] = useState(true)
  const [loadingPlans, setLoadingPlans] = useState(true)

  const [goal, setGoal] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState('')

  useEffect(() => {
    if (!wsId) return
    getBrandProfile(wsId)
      .then(b => {
        if (!b || b.onboarding_status === 'in_progress') {
          navigate(`/workspaces/${wsId}/onboarding`, { replace: true })
          return
        }
        setBrand(b)
      })
      .finally(() => setLoadingBrand(false))

    listPlans(wsId)
      .then(setPlans)
      .finally(() => setLoadingPlans(false))
  }, [wsId, navigate])

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId) return
    setGenerating(true)
    setGenError('')
    try {
      const plan = await generatePlan(wsId, goal)
      navigate(`/workspaces/${wsId}/plans/${plan.id}`)
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'فشل بدء التوليد')
      setGenerating(false)
    }
  }

  if (loadingBrand) {
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
        <span className="text-sm font-medium">{brand?.brand_name || brand?.company_name || 'مساحة العمل'}</span>
        <a
          href={import.meta.env.VITE_POSTIZ_URL || 'http://localhost:5174'}
          target="_blank"
          rel="noopener noreferrer"
          className="mr-auto text-xs text-slate-300 hover:text-white transition-colors bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg flex items-center gap-1.5"
        >
          <span>📤</span>
          <span>Postiz</span>
        </a>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* Brand Brain summary */}
        {brand && (
          <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <Link
                to={`/workspaces/${wsId}/brand-brain`}
                className="text-sm text-indigo-600 hover:text-indigo-800 font-medium"
              >
                ← عرض وتعديل
              </Link>
              <div>
                <h2 className="font-semibold text-gray-900 text-right">الذاكرة التسويقية</h2>
                <p className="text-xs text-gray-500 mt-0.5 text-right">
                  {brand.brand_name || brand.company_name} · {brand.industry || 'لم يُحدَّد القطاع'}
                </p>
              </div>
            </div>
            <div className="px-6 py-4">
              <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">النبرة</dt>
                  <dd className="text-gray-900 mt-0.5">{brand.tone || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">شرائح الجمهور</dt>
                  <dd className="text-gray-900 mt-0.5">{brand.audience_segments.length} محددة</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">المنتجات</dt>
                  <dd className="text-gray-900 mt-0.5">{brand.products.length} مدرجة</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">تجنّب</dt>
                  <dd className="text-gray-900 mt-0.5 truncate">{(brand.avoid || []).slice(0, 3).join(', ') || '—'}</dd>
                </div>
              </dl>
            </div>
          </section>
        )}

        {/* AI Assistant entry point */}
        {brand && (
          <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 flex items-center justify-between">
              <Link
                to={`/workspaces/${wsId}/chat`}
                className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-2 rounded-lg transition-colors"
              >
                ← فتح المساعد
              </Link>
              <div>
                <h2 className="font-semibold text-gray-900 text-right">المساعد الذكي</h2>
                <p className="text-xs text-gray-500 mt-0.5 text-right">اطرح أسئلة عن علامتك التجارية، ابتكر المحتوى، أنشئ مسودات، أو ابدأ خطة.</p>
              </div>
            </div>
          </section>
        )}

        {/* Generate Plan */}
        {brand && (
          <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900">توليد خطة المحتوى</h2>
              <p className="text-xs text-gray-500 mt-0.5">سيُنشئ الذكاء الاصطناعي 7 منشورات للأسبوع. تعتمد كل منشور قبل نشره.</p>
            </div>
            <div className="p-6">
              <form onSubmit={handleGenerate} className="flex gap-3">
                <button
                  type="submit"
                  disabled={generating}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
                >
                  {generating ? 'جارٍ البدء…' : 'توليد الخطة'}
                </button>
                <input
                  type="text"
                  value={goal}
                  onChange={e => setGoal(e.target.value)}
                  placeholder="هدف اختياري، مثل: إطلاق منتج جديد"
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </form>
              {genError && <p className="text-red-600 text-xs mt-2">{genError}</p>}
            </div>
          </section>
        )}

        {/* Plans List */}
        <section>
          <h2 className="font-semibold text-gray-900 mb-3">خطط المحتوى</h2>
          {loadingPlans ? (
            <div className="text-gray-400 text-sm">جارٍ التحميل…</div>
          ) : plans.length === 0 ? (
            <div className="text-center py-10 text-gray-400 bg-white border border-gray-200 rounded-xl">
              <p className="text-3xl mb-2">📅</p>
              <p className="text-sm">لا توجد خطط بعد. أنشئ أولى خططك أعلاه.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {plans.map(plan => {
                const approved = plan.posts.filter(p => ['approved', 'scheduled', 'published'].includes(p.status)).length
                const pending = plan.posts.filter(p => p.status === 'pending_approval').length
                return (
                  <Link
                    key={plan.id}
                    to={`/workspaces/${wsId}/plans/${plan.id}`}
                    className="block bg-white border border-gray-200 hover:border-indigo-300 hover:shadow-md rounded-xl p-5 transition-all group"
                  >
                    <div className="flex items-start justify-between">
                      <span className="text-gray-300 group-hover:text-indigo-400 text-xl">←</span>
                      <div className="flex-1 min-w-0 text-right">
                        <div className="flex items-center gap-2 mb-1 justify-end">
                          <span className="text-xs text-gray-400">{new Date(plan.created_at).toLocaleDateString('ar-SA')}</span>
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[plan.status] ?? 'bg-gray-100 text-gray-600'}`}>
                            {STATUS_LABEL[plan.status] ?? plan.status}
                          </span>
                        </div>
                        <p className="text-sm text-gray-700 truncate">{plan.goal || 'تعزيز الوعي بالعلامة التجارية'}</p>
                        {plan.status === 'ready' && (
                          <p className="text-xs text-gray-400 mt-1">
                            {approved} مُعتمد · {pending} في الانتظار · {plan.posts.length} إجمالي
                          </p>
                        )}
                      </div>
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
