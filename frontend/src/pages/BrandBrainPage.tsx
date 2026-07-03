import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getBrandProfile, updateBrandProfile,
  listDocuments, deleteDocument, searchKnowledge,
} from '../api'
import type { AudienceSegment, BrandProfile, KnowledgeChunk, KnowledgeDocument, ProductItem } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function run<T>(
  setBusy: (b: string | null) => void,
  label: string,
  fn: () => Promise<T>,
): Promise<T> {
  setBusy(label)
  return fn().finally(() => setBusy(null))
}

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: KnowledgeDocument['status'] }) {
  if (status === 'processing') return <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">جارٍ الفهرسة…</span>
  if (status === 'indexed') return <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">جاهز</span>
  return <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">فشل</span>
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children, action }: {
  title: string
  children: React.ReactNode
  action?: React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full px-6 py-4 border-b border-gray-100 flex items-center justify-between text-right hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {action && <div onClick={e => e.stopPropagation()}>{action}</div>}
          <span className="text-gray-400 text-sm">{open ? '▲' : '▼'}</span>
        </div>
        <span className="font-semibold text-gray-900">{title}</span>
      </button>
      {open && <div className="p-6">{children}</div>}
    </div>
  )
}

// ── Inline editable field ─────────────────────────────────────────────────────

function EditableField({ label, value, onSave, multiline = false }: {
  label: string
  value: string | null | undefined
  onSave: (v: string) => Promise<void>
  multiline?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
        {multiline ? (
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            rows={3}
            autoFocus
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
        ) : (
          <input
            type="text"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            autoFocus
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        )}
        <div className="flex gap-2 mt-2">
          <button
            type="button"
            onClick={() => { setDraft(value ?? ''); setEditing(false) }}
            className="text-gray-500 hover:text-gray-700 px-3 py-1.5 text-xs"
          >
            إلغاء
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true)
              onSave(draft).then(() => setEditing(false)).finally(() => setBusy(false))
            }}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs font-medium"
          >
            {busy ? 'جارٍ الحفظ…' : 'حفظ'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="group flex items-start justify-between gap-3">
      <button
        type="button"
        onClick={() => { setDraft(value ?? ''); setEditing(true) }}
        className="opacity-0 group-hover:opacity-100 text-xs text-indigo-600 hover:text-indigo-800 transition-opacity"
      >
        تعديل
      </button>
      <div className="flex-1 min-w-0 text-right">
        <dt className="text-xs font-medium text-gray-500 mb-0.5">{label}</dt>
        <dd className="text-sm text-gray-900">{value || <span className="text-gray-400 italic">غير محدد</span>}</dd>
      </div>
    </div>
  )
}

// ── Profile sections ──────────────────────────────────────────────────────────

function ProfileBasics({ brand, onSave }: { brand: BrandProfile; onSave: (p: Partial<BrandProfile>) => Promise<void> }) {
  return (
    <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
      <EditableField label="اسم الشركة" value={brand.company_name} onSave={v => onSave({ company_name: v })} />
      <EditableField label="اسم العلامة التجارية" value={brand.brand_name} onSave={v => onSave({ brand_name: v })} />
      <EditableField label="القطاع" value={brand.industry} onSave={v => onSave({ industry: v })} />
      <EditableField label="تحديد الموقع" value={brand.positioning} onSave={v => onSave({ positioning: v })} multiline />
    </dl>
  )
}

function ProfileProducts({ brand, onSave }: { brand: BrandProfile; onSave: (p: Partial<BrandProfile>) => Promise<void> }) {
  const products: ProductItem[] = brand.products ?? []
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<ProductItem[]>(products)
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <div className="space-y-3">
        {draft.map((p, i) => (
          <div key={i} className="border border-gray-200 rounded-lg p-3 relative">
            <button type="button" onClick={() => setDraft(d => d.filter((_, j) => j !== i))}
              className="absolute top-2 left-2 text-gray-300 hover:text-red-500 text-lg leading-none">×</button>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {[
                { k: 'name' as const, ph: 'الاسم' },
                { k: 'description' as const, ph: 'الوصف' },
                { k: 'price_point' as const, ph: 'نقطة السعر (اختياري)' },
              ].map(({ k, ph }) => (
                <input key={k} type="text" value={p[k] ?? ''} placeholder={ph}
                  onChange={e => setDraft(d => d.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x))}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400" />
              ))}
            </div>
          </div>
        ))}
        <button type="button" onClick={() => setDraft(d => [...d, { name: '', description: '' }])}
          className="text-sm text-indigo-600 hover:text-indigo-800">+ إضافة منتج</button>
        <div className="flex gap-2 mt-2">
          <button type="button" onClick={() => { setDraft(products); setEditing(false) }}
            className="text-gray-500 hover:text-gray-700 px-3 py-1.5 text-xs">إلغاء</button>
          <button type="button" disabled={busy}
            onClick={() => { setBusy(true); onSave({ products: draft }).then(() => setEditing(false)).finally(() => setBusy(false)) }}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs font-medium">
            {busy ? 'جارٍ الحفظ…' : 'حفظ'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      {products.length === 0 ? (
        <p className="text-sm text-gray-400 italic">لا توجد منتجات مدرجة.</p>
      ) : (
        <ul className="space-y-2 mb-3">
          {products.map((p, i) => (
            <li key={i} className="bg-gray-50 border border-gray-100 rounded-lg px-4 py-2.5 text-sm text-right">
              <span className="font-medium text-gray-800">{p.name}</span>
              {p.description && <span className="text-gray-500 mr-2">{p.description}</span>}
              {p.price_point && <span className="text-indigo-600 mr-2 text-xs">{p.price_point}</span>}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => { setDraft(products); setEditing(true) }}
        className="text-sm text-indigo-600 hover:text-indigo-800">تعديل المنتجات</button>
    </div>
  )
}

function ProfileAudience({ brand, onSave }: { brand: BrandProfile; onSave: (p: Partial<BrandProfile>) => Promise<void> }) {
  const segments: AudienceSegment[] = brand.audience_segments ?? []
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<AudienceSegment[]>(segments)
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <div className="space-y-3">
        {draft.map((s, i) => (
          <div key={i} className="border border-gray-200 rounded-lg p-3 relative space-y-2">
            <button type="button" onClick={() => setDraft(d => d.filter((_, j) => j !== i))}
              className="absolute top-2 left-2 text-gray-300 hover:text-red-500 text-lg leading-none">×</button>
            <input type="text" value={s.name} placeholder="اسم الشريحة"
              onChange={e => setDraft(d => d.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400" />
            <textarea value={s.description} placeholder="الوصف" rows={2}
              onChange={e => setDraft(d => d.map((x, j) => j === i ? { ...x, description: e.target.value } : x))}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400 resize-none" />
            <input type="text" value={s.pain_points.join(', ')} placeholder="نقاط الألم (مفصولة بفواصل)"
              onChange={e => setDraft(d => d.map((x, j) => j === i ? { ...x, pain_points: e.target.value.split(',').map(v => v.trim()).filter(Boolean) } : x))}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400" />
            <input type="text" value={s.channels.join(', ')} placeholder="القنوات (مفصولة بفواصل)"
              onChange={e => setDraft(d => d.map((x, j) => j === i ? { ...x, channels: e.target.value.split(',').map(v => v.trim()).filter(Boolean) } : x))}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400" />
          </div>
        ))}
        <button type="button" onClick={() => setDraft(d => [...d, { name: '', description: '', pain_points: [], channels: [] }])}
          className="text-sm text-indigo-600 hover:text-indigo-800">+ إضافة شريحة</button>
        <div className="flex gap-2 mt-2">
          <button type="button" onClick={() => { setDraft(segments); setEditing(false) }}
            className="text-gray-500 hover:text-gray-700 px-3 py-1.5 text-xs">إلغاء</button>
          <button type="button" disabled={busy}
            onClick={() => { setBusy(true); onSave({ audience_segments: draft }).then(() => setEditing(false)).finally(() => setBusy(false)) }}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs font-medium">
            {busy ? 'جارٍ الحفظ…' : 'حفظ'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      {segments.length === 0 ? (
        <p className="text-sm text-gray-400 italic">لا توجد شرائح جمهور محددة.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          {segments.map((s, i) => (
            <div key={i} className="bg-gray-50 border border-gray-100 rounded-lg p-3 text-right">
              <p className="font-medium text-gray-800 text-sm">{s.name}</p>
              {s.description && <p className="text-gray-500 text-xs mt-0.5">{s.description}</p>}
              {s.channels.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5 justify-end">
                  {s.channels.map(c => (
                    <span key={c} className="bg-indigo-50 text-indigo-700 text-xs px-1.5 py-0.5 rounded">{c}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <button type="button" onClick={() => { setDraft(segments); setEditing(true) }}
        className="text-sm text-indigo-600 hover:text-indigo-800">تعديل الجمهور</button>
    </div>
  )
}

function ProfileVoice({ brand, onSave }: { brand: BrandProfile; onSave: (p: Partial<BrandProfile>) => Promise<void> }) {
  return (
    <dl className="space-y-4">
      <EditableField label="النبرة" value={brand.tone} onSave={v => onSave({ tone: v })} />
      <EditableField label="إرشادات الصوت" value={brand.voice_guidelines} onSave={v => onSave({ voice_guidelines: v })} multiline />
      <div>
        <dt className="text-xs font-medium text-gray-500 mb-1 text-right">تجنّب</dt>
        <dd className="flex flex-wrap gap-1.5 justify-end">
          {(brand.avoid ?? []).length === 0
            ? <span className="text-sm text-gray-400 italic">لا يوجد شيء مدرج.</span>
            : (brand.avoid ?? []).map(a => (
              <span key={a} className="bg-red-50 text-red-700 text-xs px-2 py-0.5 rounded-full">{a}</span>
            ))
          }
        </dd>
      </div>
    </dl>
  )
}

function ProfileGoals({ brand, onSave }: { brand: BrandProfile; onSave: (p: Partial<BrandProfile>) => Promise<void> }) {
  const goals: string[] = brand.goals ?? []
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string[]>(goals)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <div className="space-y-3">
        <div className="flex gap-2">
          <button type="button" onClick={() => { input.trim() && (setDraft(d => [...d, input.trim()]), setInput('')) }}
            className="bg-indigo-600 text-white px-3 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">إضافة</button>
          <input type="text" value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), input.trim() && (setDraft(d => [...d, input.trim()]), setInput('')))}
            placeholder="أضف هدفاً واضغط Enter"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
        </div>
        <ul className="space-y-1.5">
          {draft.map((g, i) => (
            <li key={i} className="flex items-center justify-between bg-gray-50 border border-gray-100 rounded px-3 py-2 text-sm">
              <button type="button" onClick={() => setDraft(d => d.filter((_, j) => j !== i))}
                className="text-gray-300 hover:text-red-500 text-lg leading-none">×</button>
              <span className="text-gray-800">{g}</span>
            </li>
          ))}
        </ul>
        <div className="flex gap-2">
          <button type="button" onClick={() => { setDraft(goals); setEditing(false) }}
            className="text-gray-500 hover:text-gray-700 px-3 py-1.5 text-xs">إلغاء</button>
          <button type="button" disabled={busy}
            onClick={() => { setBusy(true); onSave({ goals: draft }).then(() => setEditing(false)).finally(() => setBusy(false)) }}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs font-medium">
            {busy ? 'جارٍ الحفظ…' : 'حفظ'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      {goals.length === 0 ? (
        <p className="text-sm text-gray-400 italic">لم تُحدَّد أهداف.</p>
      ) : (
        <ul className="space-y-1.5 mb-3">
          {goals.map((g, i) => (
            <li key={i} className="flex items-center gap-2 text-sm text-gray-800 flex-row-reverse">
              <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold flex-shrink-0">{i + 1}</span>
              {g}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => { setDraft(goals); setInput(''); setEditing(true) }}
        className="text-sm text-indigo-600 hover:text-indigo-800">تعديل الأهداف</button>
    </div>
  )
}

// ── Knowledge documents section ───────────────────────────────────────────────

function KnowledgeSection({ wsId }: { wsId: string }) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(() => listDocuments(wsId).then(setDocs), [wsId])

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

  const handleDelete = async (docId: string) => {
    await run(setBusy, docId, () => deleteDocument(wsId, docId))
    await refresh()
  }

  if (docs.length === 0) {
    return (
      <p className="text-sm text-gray-400 italic">
        لم يُرفع أي مستند. <Link to={`/workspaces/${wsId}/onboarding`} className="text-indigo-600 hover:text-indigo-800">الذهاب إلى الإعداد</Link> لإضافة المواد.
      </p>
    )
  }

  return (
    <ul className="space-y-2">
      {docs.map(doc => (
        <li key={doc.id} className="flex items-center justify-between bg-gray-50 border border-gray-100 rounded-lg px-4 py-3">
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              type="button"
              disabled={busy === doc.id}
              onClick={() => handleDelete(doc.id)}
              className="text-xs text-red-500 hover:text-red-700 disabled:opacity-50"
            >
              {busy === doc.id ? 'جارٍ الحذف…' : 'حذف'}
            </button>
            <StatusBadge status={doc.status} />
          </div>
          <div className="flex items-center gap-3 flex-1 min-w-0 justify-end">
            <div className="min-w-0 text-right">
              <p className="text-sm text-gray-800 truncate font-medium">{doc.filename}</p>
              <p className="text-xs text-gray-400">{doc.doc_type} · {new Date(doc.uploaded_at).toLocaleDateString('ar-SA')}</p>
            </div>
            <span className="text-2xl">📄</span>
          </div>
        </li>
      ))}
    </ul>
  )
}

// ── Knowledge search section ──────────────────────────────────────────────────

function KnowledgeSearch({ wsId }: { wsId: string }) {
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounce(query, 300)
  const [results, setResults] = useState<KnowledgeChunk[]>([])
  const [searching, setSearching] = useState(false)

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setResults([])
      return
    }
    setSearching(true)
    searchKnowledge(wsId, debouncedQuery)
      .then(setResults)
      .catch(() => setResults([]))
      .finally(() => setSearching(false))
  }, [wsId, debouncedQuery])

  return (
    <div className="space-y-3">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="ابحث في معرفة علامتك التجارية…"
          className="w-full border border-gray-300 rounded-lg pr-9 pl-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
        {searching && <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs">جارٍ البحث…</span>}
      </div>
      {results.length > 0 && (
        <ul className="space-y-2">
          {results.map(chunk => (
            <li key={chunk.id} className="bg-gray-50 border border-gray-100 rounded-lg p-4">
              <p className="text-sm text-gray-800 leading-relaxed line-clamp-4">{chunk.content}</p>
            </li>
          ))}
        </ul>
      )}
      {debouncedQuery.trim() && !searching && results.length === 0 && (
        <p className="text-sm text-gray-400 italic">لا توجد نتائج.</p>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BrandBrainPage() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [brand, setBrand] = useState<BrandProfile | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!wsId) return
    getBrandProfile(wsId)
      .then(b => {
        if (!b || b.onboarding_status !== 'active') {
          navigate(`/workspaces/${wsId}/onboarding`, { replace: true })
          return
        }
        setBrand(b)
      })
      .finally(() => setLoading(false))
  }, [wsId, navigate])

  const save = useCallback(async (patch: Partial<BrandProfile>) => {
    if (!wsId) return
    const updated = await updateBrandProfile(wsId, patch)
    setBrand(updated)
  }, [wsId])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-400 text-sm">جارٍ التحميل…</div>
      </div>
    )
  }

  if (!brand) return null

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">
          {brand.brand_name || brand.company_name || 'مساحة العمل'}
        </Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">الذاكرة التسويقية</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-4">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Link
              to={`/workspaces/${wsId}/onboarding`}
              className="text-sm text-indigo-600 hover:text-indigo-800 border border-indigo-200 hover:border-indigo-400 px-4 py-2 rounded-lg transition-colors"
            >
              إعادة الإعداد
            </Link>
            <Link
              to={`/workspaces/${wsId}/chat`}
              className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-2 rounded-lg transition-colors"
            >
              اسأل الذكاء الاصطناعي
            </Link>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 text-right">الذاكرة التسويقية</h1>
            <p className="text-sm text-gray-500 mt-1 text-right">كل ما يعرفه الذكاء الاصطناعي عن علامتك التجارية.</p>
          </div>
        </div>

        <Section title="أساسيات الشركة">
          <ProfileBasics brand={brand} onSave={save} />
        </Section>

        <Section title="المنتجات والخدمات">
          <ProfileProducts brand={brand} onSave={save} />
        </Section>

        <Section title="الجمهور">
          <ProfileAudience brand={brand} onSave={save} />
        </Section>

        <Section title="صوت العلامة التجارية">
          <ProfileVoice brand={brand} onSave={save} />
        </Section>

        <Section title="الأهداف">
          <ProfileGoals brand={brand} onSave={save} />
        </Section>

        <Section title="مستندات المعرفة">
          {wsId && <KnowledgeSection wsId={wsId} />}
        </Section>

        <Section title="البحث في المعرفة">
          {wsId && <KnowledgeSearch wsId={wsId} />}
        </Section>
      </main>
    </div>
  )
}
