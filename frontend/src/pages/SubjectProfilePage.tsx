import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getAnalysisSubject, updateAnalysisSubject, uploadDocument, listDocuments, deleteDocument } from '../api'
import type { AnalysisSubject, KnowledgeDocument } from '../types'

export default function SubjectProfilePage() {
  const { wsId } = useParams<{ wsId: string }>()

  const [subject, setSubject] = useState<AnalysisSubject | null>(null)
  const [docs, setDocs] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [uploading, setUploading] = useState(false)

  const [form, setForm] = useState({
    subject_name: '',
    legal_name: '',
    subject_type: '',
    industry: '',
    subject_description: '',
    areas_of_interest_raw: '',
    tracked_competitors: [{ name: '', notes: '' }],
  })

  useEffect(() => {
    if (!wsId) return
    getAnalysisSubject(wsId).then(s => {
      if (!s) return
      setSubject(s)
      setForm({
        subject_name: s.subject_name ?? '',
        legal_name: s.legal_name ?? '',
        subject_type: s.subject_type ?? 'company',
        industry: s.industry ?? '',
        subject_description: s.subject_description ?? '',
        areas_of_interest_raw: s.areas_of_interest.join('، '),
        tracked_competitors: s.tracked_competitors.length > 0
          ? s.tracked_competitors.map(c => ({ name: c.name, notes: c.notes ?? '' }))
          : [{ name: '', notes: '' }],
      })
    }).finally(() => setLoading(false))

    listDocuments(wsId).then(setDocs).catch(() => {})
  }, [wsId])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await updateAnalysisSubject(wsId, {
        subject_name: form.subject_name || null,
        legal_name: form.legal_name || null,
        subject_type: form.subject_type || null,
        industry: form.industry || null,
        subject_description: form.subject_description || null,
        areas_of_interest: form.areas_of_interest_raw.split(/[,،]/).map(s => s.trim()).filter(Boolean),
        tracked_competitors: form.tracked_competitors
          .filter(c => c.name.trim())
          .map(c => ({ name: c.name, notes: c.notes || null })),
        setup_status: 'complete',
      })
      setSubject(updated)
      setSuccess('تم الحفظ بنجاح')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فشل الحفظ')
    } finally {
      setSaving(false)
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !wsId) return
    setUploading(true)
    try {
      const doc = await uploadDocument(wsId, file)
      setDocs(prev => [doc, ...prev])
    } catch { /* ignore */ } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleDeleteDoc(docId: string) {
    if (!wsId) return
    await deleteDocument(wsId, docId).catch(() => {})
    setDocs(prev => prev.filter(d => d.id !== docId))
  }

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
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">ملف موضوع التحليل</span>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-10 space-y-8">

        {/* Subject identity form */}
        <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900 text-right">هوية موضوع التحليل</h2>
          </div>
          <form onSubmit={handleSave} className="p-6 space-y-5">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1 text-right">اسم الموضوع</label>
                <input
                  value={form.subject_name}
                  onChange={e => setForm(p => ({ ...p, subject_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الاسم القانوني</label>
                <input
                  value={form.legal_name}
                  onChange={e => setForm(p => ({ ...p, legal_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1 text-right">النوع</label>
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
                <label className="block text-xs font-medium text-gray-600 mb-1 text-right">القطاع / السوق</label>
                <input
                  value={form.industry}
                  onChange={e => setForm(p => ({ ...p, industry: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">وصف الموضوع</label>
              <textarea
                value={form.subject_description}
                onChange={e => setForm(p => ({ ...p, subject_description: e.target.value }))}
                rows={3}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">محاور الاهتمام (مفصولة بفواصل)</label>
              <input
                value={form.areas_of_interest_raw}
                onChange={e => setForm(p => ({ ...p, areas_of_interest_raw: e.target.value }))}
                placeholder="مثال: حجم السوق، الوضع التنافسي"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>

            {/* Tracked competitors */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-2 text-right">المنافسون المتتبَّعون</label>
              <div className="space-y-2">
                {form.tracked_competitors.map((c, i) => (
                  <div key={i} className="flex gap-2 items-center">
                    <button
                      type="button"
                      onClick={() => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.filter((_, j) => j !== i) }))}
                      className="text-gray-300 hover:text-red-400 text-sm flex-shrink-0"
                      disabled={form.tracked_competitors.length === 1}
                    >✕</button>
                    <input
                      value={c.name}
                      onChange={e => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.map((cc, j) => j === i ? { ...cc, name: e.target.value } : cc) }))}
                      placeholder="اسم المنافس"
                      className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm text-right focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    />
                    <input
                      value={c.notes}
                      onChange={e => setForm(p => ({ ...p, tracked_competitors: p.tracked_competitors.map((cc, j) => j === i ? { ...cc, notes: e.target.value } : cc) }))}
                      placeholder="ملاحظة"
                      className="w-32 border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-right text-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                    />
                  </div>
                ))}
                {form.tracked_competitors.length < 10 && (
                  <button
                    type="button"
                    onClick={() => setForm(p => ({ ...p, tracked_competitors: [...p.tracked_competitors, { name: '', notes: '' }] }))}
                    className="text-xs text-indigo-600 hover:text-indigo-800"
                  >+ إضافة منافس</button>
                )}
              </div>
            </div>

            {error && <p className="text-xs text-red-500 text-right">{error}</p>}
            {success && <p className="text-xs text-green-600 text-right">{success}</p>}

            <div className="flex justify-start">
              <button
                type="submit"
                disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium px-6 py-2 rounded-lg transition-colors"
              >
                {saving ? 'جارٍ الحفظ…' : 'حفظ'}
              </button>
            </div>
          </form>
        </section>

        {/* Documents */}
        <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
            <label className="cursor-pointer text-sm text-indigo-600 hover:text-indigo-800 font-medium">
              {uploading ? 'جارٍ الرفع…' : '+ رفع مستند'}
              <input type="file" className="hidden" onChange={handleUpload} disabled={uploading} />
            </label>
            <h2 className="font-semibold text-gray-900 text-right">قاعدة المعرفة</h2>
          </div>
          <div className="divide-y divide-gray-50">
            {docs.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-8">لا توجد مستندات. ارفع تقارير أو ملفات PDF لتعزيز التحليلات.</p>
            )}
            {docs.map(d => (
              <div key={d.id} className="px-6 py-3 flex items-center justify-between">
                <button onClick={() => handleDeleteDoc(d.id)} className="text-gray-300 hover:text-red-400 text-xs">حذف</button>
                <div className="text-right">
                  <p className="text-sm text-gray-800">{d.filename}</p>
                  <p className="text-xs text-gray-400">{d.status === 'indexed' ? 'مُفهرس' : d.status === 'processing' ? 'جارٍ المعالجة' : 'فشل'} · {d.doc_type}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

      </main>
    </div>
  )
}
