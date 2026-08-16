import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { updateAnalysisSubject } from '../api'

const AREAS_OPTIONS = [
  'حجم السوق',
  'الوضع التنافسي',
  'اتجاهات النمو',
  'البيئة التنظيمية',
  'مشهد الاستثمار',
  'المشهد التكنولوجي',
]

interface FormState {
  subject_name: string
  legal_name: string
  subject_type: string
  industry: string
  subject_description: string
  tracked_competitors: { name: string; notes: string }[]
  areas_of_interest: string[]
}

export default function SetupWizard() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [form, setForm] = useState<FormState>({
    subject_name: '',
    legal_name: '',
    subject_type: 'company',
    industry: '',
    subject_description: '',
    tracked_competitors: [{ name: '', notes: '' }],
    areas_of_interest: [],
  })

  async function save(status: 'in_progress' | 'complete') {
    if (!wsId) return
    setSaving(true); setError('')
    try {
      await updateAnalysisSubject(wsId, {
        subject_name: form.subject_name || null,
        legal_name: form.legal_name || null,
        subject_type: form.subject_type || null,
        industry: form.industry || null,
        subject_description: form.subject_description || null,
        tracked_competitors: form.tracked_competitors.filter(c => c.name.trim()).map(c => ({ name: c.name, notes: c.notes || null })),
        areas_of_interest: form.areas_of_interest,
        setup_status: status,
      })
      navigate(`/workspaces/${wsId}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فشل الحفظ')
    } finally {
      setSaving(false)
    }
  }

  const steps = [
    { label: 'الموضوع' },
    { label: 'الوصف' },
    { label: 'المنافسون' },
    { label: 'محاور الاهتمام' },
  ]

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">إعداد موضوع التحليل</span>
      </header>

      <div className="flex-1 flex items-start justify-center pt-12 px-4">
        <div className="w-full max-w-lg">

          {/* Step indicator */}
          <div className="flex items-center gap-2 mb-8 justify-center">
            {steps.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors ${i === step ? 'bg-indigo-600 text-white' : i < step ? 'bg-indigo-200 text-indigo-700' : 'bg-gray-200 text-gray-500'}`}>
                  {i + 1}
                </div>
                {i < steps.length - 1 && <div className={`w-8 h-px ${i < step ? 'bg-indigo-300' : 'bg-gray-200'}`} />}
              </div>
            ))}
          </div>

          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-8">

            {/* Step 0 — What are you analyzing? */}
            {step === 0 && (
              <div className="space-y-5">
                <div className="text-right">
                  <h2 className="text-lg font-semibold text-gray-900">ما الذي تريد تحليله؟</h2>
                  <p className="text-sm text-gray-500 mt-1">أخبرنا بالموضوع الذي تريد دراسته — شركة، منتج، أو قطاع.</p>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1 text-right">اسم الموضوع *</label>
                    <input
                      type="text"
                      value={form.subject_name}
                      onChange={e => setForm(p => ({ ...p, subject_name: e.target.value }))}
                      placeholder="مثال: شركة أكمي، منتج X، قطاع التوصيل"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1 text-right">النوع</label>
                    <select
                      value={form.subject_type}
                      onChange={e => setForm(p => ({ ...p, subject_type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    >
                      <option value="company">شركة</option>
                      <option value="product">منتج</option>
                      <option value="sector">قطاع</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1 text-right">القطاع / السوق</label>
                    <input
                      type="text"
                      value={form.industry}
                      onChange={e => setForm(p => ({ ...p, industry: e.target.value }))}
                      placeholder="مثال: تقنية مالية، توصيل طعام، رعاية صحية"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1 text-right">الاسم القانوني (اختياري)</label>
                    <input
                      type="text"
                      value={form.legal_name}
                      onChange={e => setForm(p => ({ ...p, legal_name: e.target.value }))}
                      placeholder="الاسم الرسمي إن اختلف"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 1 — Description */}
            {step === 1 && (
              <div className="space-y-5">
                <div className="text-right">
                  <h2 className="text-lg font-semibold text-gray-900">كيف تصف هذا الموضوع؟</h2>
                  <p className="text-sm text-gray-500 mt-1">2–3 جمل تصف ما يفعله أو ما يميزه. هذا يساعد المحلل على الفهم السياقي.</p>
                </div>
                <textarea
                  value={form.subject_description}
                  onChange={e => setForm(p => ({ ...p, subject_description: e.target.value }))}
                  rows={5}
                  placeholder="اكتب وصفاً موجزاً…"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
                />
              </div>
            )}

            {/* Step 2 — Competitors */}
            {step === 2 && (
              <div className="space-y-5">
                <div className="text-right">
                  <h2 className="text-lg font-semibold text-gray-900">من هم المنافسون الرئيسيون؟</h2>
                  <p className="text-sm text-gray-500 mt-1">أضف حتى 5 منافسين تريد متابعتهم في التحليلات.</p>
                </div>
                <div className="space-y-3">
                  {form.tracked_competitors.map((c, i) => (
                    <div key={i} className="flex gap-2 items-start">
                      <button
                        onClick={() => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.filter((_, j) => j !== i) }))}
                        className="mt-2 text-gray-300 hover:text-red-400 text-sm"
                        disabled={form.tracked_competitors.length === 1}
                      >✕</button>
                      <div className="flex-1 space-y-1.5">
                        <input
                          type="text"
                          value={c.name}
                          onChange={e => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.map((cc, j) => j === i ? { ...cc, name: e.target.value } : cc) }))}
                          placeholder={`منافس ${i + 1}`}
                          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                        />
                        <input
                          type="text"
                          value={c.notes}
                          onChange={e => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.map((cc, j) => j === i ? { ...cc, notes: e.target.value } : cc) }))}
                          placeholder="ملاحظة اختيارية"
                          className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-right text-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                        />
                      </div>
                    </div>
                  ))}
                  {form.tracked_competitors.length < 5 && (
                    <button
                      onClick={() => setForm(p => ({ ...p, tracked_competitors: [...p.tracked_competitors, { name: '', notes: '' }] }))}
                      className="text-sm text-indigo-600 hover:text-indigo-800"
                    >+ إضافة منافس</button>
                  )}
                </div>
              </div>
            )}

            {/* Step 3 — Areas of interest */}
            {step === 3 && (
              <div className="space-y-5">
                <div className="text-right">
                  <h2 className="text-lg font-semibold text-gray-900">ما الذي تريد فهمه أكثر؟</h2>
                  <p className="text-sm text-gray-500 mt-1">اختر المحاور التي تهمك. يمكنك اختيار أكثر من محور.</p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {AREAS_OPTIONS.map(a => (
                    <button
                      key={a}
                      onClick={() => setForm(p => ({
                        ...p,
                        areas_of_interest: p.areas_of_interest.includes(a)
                          ? p.areas_of_interest.filter(x => x !== a)
                          : [...p.areas_of_interest, a],
                      }))}
                      className={`text-sm px-3 py-2 rounded-lg border transition-colors text-right ${form.areas_of_interest.includes(a) ? 'bg-indigo-50 border-indigo-400 text-indigo-700' : 'bg-white border-gray-200 text-gray-700 hover:border-indigo-300'}`}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {error && <p className="text-xs text-red-500 text-center mt-4">{error}</p>}

            {/* Navigation */}
            <div className="flex items-center justify-between mt-8">
              <button
                onClick={() => save('in_progress')}
                className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
                disabled={saving}
              >
                تخطي الإعداد
              </button>
              <div className="flex gap-3">
                {step > 0 && (
                  <button
                    onClick={() => setStep(p => p - 1)}
                    className="text-sm text-gray-600 hover:text-gray-900 px-4 py-2 rounded-lg border border-gray-300 hover:border-gray-400 transition-colors"
                  >
                    السابق
                  </button>
                )}
                {step < steps.length - 1 ? (
                  <button
                    onClick={() => setStep(p => p + 1)}
                    className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-5 py-2 rounded-lg transition-colors"
                  >
                    التالي
                  </button>
                ) : (
                  <button
                    onClick={() => save('complete')}
                    disabled={saving}
                    className="text-sm bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium px-5 py-2 rounded-lg transition-colors"
                  >
                    {saving ? 'جارٍ الحفظ…' : 'ابدأ التحليل'}
                  </button>
                )}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
