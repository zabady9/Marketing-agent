import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getBrandProfile, updateBrandProfile, uploadDocument, listDocuments } from '../api'
import type { AudienceSegment, KnowledgeDocument, ProductItem } from '../types'

// ── Types ───────────────────────────────────────────────────────────────────

interface FormData {
  company_name: string
  brand_name: string
  industry: string
  positioning: string
  products: ProductItem[]
  audience_segments: AudienceSegment[]
  tone: string
  voice_guidelines: string
  avoid: string[]
  goals: string[]
}

const EMPTY_PRODUCT: ProductItem = { name: '', description: '', price_point: '' }
const EMPTY_SEGMENT: AudienceSegment = { name: '', description: '', pain_points: [], channels: [] }

const STEPS = [
  'أساسيات الشركة',
  'المنتجات',
  'الجمهور',
  'صوت العلامة التجارية',
  'الأهداف',
  'رفع المواد',
  'مراجعة وتأكيد',
]

// ── Helpers ──────────────────────────────────────────────────────────────────

function run<T>(
  setBusy: (b: string | null) => void,
  label: string,
  fn: () => Promise<T>,
): Promise<T> {
  setBusy(label)
  return fn().finally(() => setBusy(null))
}

// ── Step components ───────────────────────────────────────────────────────────

function StepCompanyBasics({ data, onChange }: { data: FormData; onChange: (p: Partial<FormData>) => void }) {
  return (
    <div className="space-y-4">
      {([
        { label: 'اسم الشركة', key: 'company_name', placeholder: 'مثال: شركة الأمل' },
        { label: 'اسم العلامة التجارية', key: 'brand_name', placeholder: 'مثال: الأمل' },
        { label: 'القطاع', key: 'industry', placeholder: 'مثال: برمجيات، تجارة إلكترونية، رعاية صحية' },
      ] as const).map(({ label, key, placeholder }) => (
        <div key={key}>
          <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
          <input
            type="text"
            value={data[key]}
            onChange={e => onChange({ [key]: e.target.value })}
            placeholder={placeholder}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      ))}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">بيان تحديد الموقع</label>
        <textarea
          value={data.positioning}
          onChange={e => onChange({ positioning: e.target.value })}
          placeholder="كيف تصف علامتك التجارية في جملة واحدة؟ مثال: الأداة المدعومة بالذكاء الاصطناعي التي تساعد الفرق الصغيرة على النشر كالعلامات الكبيرة."
          rows={3}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
        />
      </div>
    </div>
  )
}

function StepProducts({ data, onChange }: { data: FormData; onChange: (p: Partial<FormData>) => void }) {
  const update = (idx: number, patch: Partial<ProductItem>) => {
    const updated = data.products.map((p, i) => i === idx ? { ...p, ...patch } : p)
    onChange({ products: updated })
  }
  const add = () => onChange({ products: [...data.products, { ...EMPTY_PRODUCT }] })
  const remove = (idx: number) => onChange({ products: data.products.filter((_, i) => i !== idx) })

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">أدرج المنتجات أو الخدمات الرئيسية التي تريد الترويج لها.</p>
      {data.products.map((p, idx) => (
        <div key={idx} className="border border-gray-200 rounded-lg p-4 space-y-3 relative">
          <button
            type="button"
            onClick={() => remove(idx)}
            className="absolute top-3 left-3 text-gray-300 hover:text-red-500 text-lg leading-none"
          >×</button>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">اسم المنتج / الخدمة</label>
            <input
              type="text"
              value={p.name}
              onChange={e => update(idx, { name: e.target.value })}
              placeholder="مثال: الباقة الاحترافية"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">الوصف</label>
            <input
              type="text"
              value={p.description}
              onChange={e => update(idx, { description: e.target.value })}
              placeholder="وصف بسطر واحد"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">نقطة السعر <span className="text-gray-400">(اختياري)</span></label>
            <input
              type="text"
              value={p.price_point ?? ''}
              onChange={e => update(idx, { price_point: e.target.value })}
              placeholder="مثال: 49$ شهرياً، مجاني + مدفوع، حسب الطلب"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="w-full border-2 border-dashed border-gray-200 rounded-lg py-3 text-sm text-gray-500 hover:border-indigo-300 hover:text-indigo-600 transition-colors"
      >
        + إضافة منتج أو خدمة
      </button>
    </div>
  )
}

function StepAudience({ data, onChange }: { data: FormData; onChange: (p: Partial<FormData>) => void }) {
  const update = (idx: number, patch: Partial<AudienceSegment>) => {
    const updated = data.audience_segments.map((s, i) => i === idx ? { ...s, ...patch } : s)
    onChange({ audience_segments: updated })
  }
  const add = () => onChange({ audience_segments: [...data.audience_segments, { ...EMPTY_SEGMENT }] })
  const remove = (idx: number) => onChange({ audience_segments: data.audience_segments.filter((_, i) => i !== idx) })

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">حدّد شرائح جمهورك المستهدف. يمكنك إضافة أكثر من شريحة.</p>
      {data.audience_segments.map((s, idx) => (
        <div key={idx} className="border border-gray-200 rounded-lg p-4 space-y-3 relative">
          <button
            type="button"
            onClick={() => remove(idx)}
            className="absolute top-3 left-3 text-gray-300 hover:text-red-500 text-lg leading-none"
          >×</button>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">اسم الشريحة</label>
            <input
              type="text"
              value={s.name}
              onChange={e => update(idx, { name: e.target.value })}
              placeholder="مثال: مؤسسو الشركات الصغيرة"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">الوصف</label>
            <textarea
              value={s.description}
              onChange={e => update(idx, { description: e.target.value })}
              placeholder="من هم؟ ماذا يعملون؟"
              rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">نقاط الألم <span className="text-gray-400">(مفصولة بفواصل)</span></label>
            <input
              type="text"
              value={s.pain_points.join(', ')}
              onChange={e => update(idx, { pain_points: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
              placeholder="مثال: عمل يدوي كثير، أدوات مكلفة"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">القنوات المفضلة <span className="text-gray-400">(مفصولة بفواصل)</span></label>
            <input
              type="text"
              value={s.channels.join(', ')}
              onChange={e => update(idx, { channels: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
              placeholder="مثال: لينكدإن، بريد إلكتروني، إكس"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="w-full border-2 border-dashed border-gray-200 rounded-lg py-3 text-sm text-gray-500 hover:border-indigo-300 hover:text-indigo-600 transition-colors"
      >
        + إضافة شريحة جمهور
      </button>
    </div>
  )
}

function StepBrandVoice({ data, onChange }: { data: FormData; onChange: (p: Partial<FormData>) => void }) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">النبرة</label>
        <input
          type="text"
          value={data.tone}
          onChange={e => onChange({ tone: e.target.value })}
          placeholder="مثال: احترافي، ذكي، مباشر، متعاطف"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">إرشادات الصوت</label>
        <textarea
          value={data.voice_guidelines}
          onChange={e => onChange({ voice_guidelines: e.target.value })}
          placeholder="صف كيف تبدو علامتك التجارية. ما أسلوب الكتابة؟ ما العبارات المناسبة وغير المناسبة؟"
          rows={4}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">كلمات/مواضيع للتجنّب <span className="text-gray-400">(مفصولة بفواصل)</span></label>
        <input
          type="text"
          value={data.avoid.join(', ')}
          onChange={e => onChange({ avoid: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
          placeholder="مثال: أسماء المنافسين، السياسة، المصطلحات التقنية"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
    </div>
  )
}

function StepGoals({ data, onChange }: { data: FormData; onChange: (p: Partial<FormData>) => void }) {
  const [input, setInput] = useState('')
  const add = () => {
    const trimmed = input.trim()
    if (!trimmed) return
    onChange({ goals: [...data.goals, trimmed] })
    setInput('')
  }
  const remove = (idx: number) => onChange({ goals: data.goals.filter((_, i) => i !== idx) })

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">ما أولويات تسويقك الحالية؟</p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={add}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          إضافة
        </button>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), add())}
          placeholder="مثال: زيادة متابعي لينكدإن، إطلاق منتج جديد"
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
      {data.goals.length > 0 && (
        <ul className="space-y-2">
          {data.goals.map((g, idx) => (
            <li key={idx} className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm">
              <button
                type="button"
                onClick={() => remove(idx)}
                className="text-gray-300 hover:text-red-500 text-lg leading-none"
              >×</button>
              <span className="text-gray-800">{g}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StepUpload({ wsId }: { wsId: string }) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(() =>
    listDocuments(wsId).then(setDocs), [wsId])

  useEffect(() => {
    refresh()
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [refresh])

  useEffect(() => {
    const hasProcessing = docs.some(d => d.status === 'processing')
    if (hasProcessing && !pollingRef.current) {
      pollingRef.current = setInterval(refresh, 3000)
    } else if (!hasProcessing && pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [docs, refresh])

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      await Promise.all(
        Array.from(files).map(f => uploadDocument(wsId, f))
      )
      await refresh()
    } finally {
      setUploading(false)
    }
  }

  const statusBadge = (s: KnowledgeDocument['status']) => {
    if (s === 'processing') return <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">جارٍ الفهرسة…</span>
    if (s === 'indexed') return <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">جاهز</span>
    return <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">فشل</span>
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        ارفع إرشادات العلامة التجارية، ملفات العروض، تقارير الحملات، أو أي مواد تصف علامتك التجارية.
        الصيغ المدعومة: PDF, DOCX, TXT.
      </p>

      {/* Drop zone */}
      <div
        className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-indigo-300 transition-colors"
        onClick={() => fileInputRef.current?.click()}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); handleFiles(e.dataTransfer.files) }}
      >
        <p className="text-3xl mb-2">📎</p>
        <p className="text-sm text-gray-500">
          {uploading ? 'جارٍ الرفع…' : 'انقر أو اسحب الملفات هنا'}
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt"
          className="hidden"
          onChange={e => handleFiles(e.target.files)}
        />
      </div>

      {/* Uploaded documents */}
      {docs.length > 0 && (
        <ul className="space-y-2">
          {docs.map(doc => (
            <li key={doc.id} className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-4 py-2.5 text-sm">
              {statusBadge(doc.status)}
              <span className="text-gray-800 truncate flex-1 ml-3">{doc.filename}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StepReview({ data, wsId, onGoToStep }: {
  data: FormData
  wsId: string
  onGoToStep: (step: number) => void
}) {
  const sections = [
    { label: 'أساسيات الشركة', step: 0, items: [
      ['الشركة', data.company_name || '—'],
      ['العلامة التجارية', data.brand_name || '—'],
      ['القطاع', data.industry || '—'],
      ['تحديد الموقع', data.positioning || '—'],
    ]},
    { label: 'المنتجات', step: 1, items: data.products.map(p => [p.name, p.description]) },
    { label: 'الجمهور', step: 2, items: data.audience_segments.map(s => [s.name, s.description]) },
    { label: 'صوت العلامة التجارية', step: 3, items: [
      ['النبرة', data.tone || '—'],
      ['تجنّب', data.avoid.join(', ') || '—'],
    ]},
    { label: 'الأهداف', step: 4, items: data.goals.map(g => ['', g]) },
  ]

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">راجع كل شيء قبل تفعيل الذاكرة التسويقية.</p>
      {sections.map(({ label, step, items }) => (
        <div key={label} className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-2.5 flex items-center justify-between">
            <button
              type="button"
              onClick={() => onGoToStep(step)}
              className="text-xs text-indigo-600 hover:text-indigo-800"
            >
              تعديل
            </button>
            <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{label}</span>
          </div>
          {items.length === 0 ? (
            <p className="px-4 py-3 text-sm text-gray-400">لم يُضَف شيء بعد.</p>
          ) : (
            <dl className="px-4 py-3 space-y-1">
              {items.map(([k, v], i) => (
                <div key={i} className="flex gap-2 text-sm justify-end">
                  <dd className="text-gray-900 flex-1 text-right">{v}</dd>
                  {k && <dt className="text-gray-500 min-w-[80px] text-right">{k}:</dt>}
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function OnboardingWizard() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')

  const [formData, setFormData] = useState<FormData>({
    company_name: '',
    brand_name: '',
    industry: '',
    positioning: '',
    products: [],
    audience_segments: [],
    tone: '',
    voice_guidelines: '',
    avoid: [],
    goals: [],
  })

  useEffect(() => {
    if (!wsId) return
    getBrandProfile(wsId).then(bp => {
      if (!bp) return
      setFormData(f => ({
        ...f,
        company_name: bp.company_name ?? '',
        brand_name: bp.brand_name ?? '',
        industry: bp.industry ?? '',
        positioning: bp.positioning ?? '',
        products: bp.products as ProductItem[],
        audience_segments: bp.audience_segments as AudienceSegment[],
        tone: bp.tone ?? '',
        voice_guidelines: bp.voice_guidelines ?? '',
        avoid: bp.avoid ?? [],
        goals: bp.goals ?? [],
      }))
    })
  }, [wsId])

  const patch = (p: Partial<FormData>) => setFormData(f => ({ ...f, ...p }))

  async function saveAndAdvance() {
    if (!wsId) return
    setError('')
    const nextStep = step + 1
    const isReviewStep = nextStep === STEPS.length - 1

    await run(setBusy, 'جارٍ الحفظ…', () =>
      updateBrandProfile(wsId, {
        ...formData,
        products: formData.products,
        audience_segments: formData.audience_segments,
        onboarding_status: isReviewStep ? 'pending_review' : 'in_progress',
      })
    ).catch(err => {
      setError(err instanceof Error ? err.message : 'فشل الحفظ')
      throw err
    })

    setStep(nextStep)
  }

  async function confirm() {
    if (!wsId) return
    setError('')
    await run(setBusy, 'جارٍ التفعيل…', () =>
      updateBrandProfile(wsId, { onboarding_status: 'active' })
    ).catch(err => {
      setError(err instanceof Error ? err.message : 'فشل التأكيد')
      throw err
    })
    navigate(`/workspaces/${wsId}/brand-brain`, { replace: true })
  }

  const isLastStep = step === STEPS.length - 1
  const isUploadStep = step === STEPS.length - 2

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">إعداد الذاكرة التسويقية</span>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-10">
        {/* Progress bar */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500">{STEPS[step]}</span>
            <span className="text-xs text-gray-500 font-medium">الخطوة {step + 1} من {STEPS.length}</span>
          </div>
          <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all duration-300"
              style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
            />
          </div>
          {/* Step pills */}
          <div className="flex gap-1 mt-3">
            {STEPS.map((s, i) => (
              <button
                key={i}
                type="button"
                onClick={() => i < step && setStep(i)}
                disabled={i > step}
                className={`flex-1 h-1 rounded-full transition-colors ${
                  i < step ? 'bg-indigo-400 cursor-pointer' : i === step ? 'bg-indigo-600' : 'bg-gray-200'
                }`}
                title={s}
              />
            ))}
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100">
            <h1 className="text-lg font-semibold text-gray-900">{STEPS[step]}</h1>
          </div>
          <div className="p-6">
            {step === 0 && <StepCompanyBasics data={formData} onChange={patch} />}
            {step === 1 && <StepProducts data={formData} onChange={patch} />}
            {step === 2 && <StepAudience data={formData} onChange={patch} />}
            {step === 3 && <StepBrandVoice data={formData} onChange={patch} />}
            {step === 4 && <StepGoals data={formData} onChange={patch} />}
            {step === 5 && wsId && <StepUpload wsId={wsId} />}
            {step === 6 && wsId && (
              <StepReview data={formData} wsId={wsId} onGoToStep={setStep} />
            )}

            {error && <p className="text-red-600 text-xs mt-4">{error}</p>}
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between">
            {isLastStep ? (
              <button
                type="button"
                onClick={confirm}
                disabled={!!busy}
                className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                {busy || 'تفعيل الذاكرة التسويقية'}
              </button>
            ) : isUploadStep ? (
              <button
                type="button"
                onClick={saveAndAdvance}
                disabled={!!busy}
                className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                {busy || 'مراجعة'}
              </button>
            ) : (
              <button
                type="button"
                onClick={saveAndAdvance}
                disabled={!!busy}
                className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                {busy || '← التالي'}
              </button>
            )}

            <button
              type="button"
              onClick={() => setStep(s => s - 1)}
              disabled={step === 0}
              className="text-sm text-gray-500 hover:text-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              رجوع →
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
