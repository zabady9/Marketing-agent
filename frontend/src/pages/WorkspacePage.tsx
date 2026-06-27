import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getBrand, upsertBrand, listPlans, generatePlan } from '../api'
import type { BrandProfile, Plan } from '../types'

const STATUS_COLOR: Record<string, string> = {
  generating: 'bg-yellow-100 text-yellow-700',
  ready: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

export default function WorkspacePage() {
  const { wsId } = useParams<{ wsId: string }>()
  const navigate = useNavigate()

  const [brand, setBrand] = useState<BrandProfile | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loadingBrand, setLoadingBrand] = useState(true)
  const [loadingPlans, setLoadingPlans] = useState(true)

  // Brand form
  const [editingBrand, setEditingBrand] = useState(false)
  const [brandForm, setBrandForm] = useState({ name: '', audience: '', tone: '', language: 'en', avoid: '' })
  const [savingBrand, setSavingBrand] = useState(false)

  // Generate
  const [goal, setGoal] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState('')

  useEffect(() => {
    if (!wsId) return
    getBrand(wsId)
      .then(b => {
        setBrand(b)
        if (b) setBrandForm({ name: b.name, audience: b.audience, tone: b.tone, language: b.language, avoid: (b.avoid || []).join(', ') })
        else setEditingBrand(true)
      })
      .finally(() => setLoadingBrand(false))

    listPlans(wsId)
      .then(setPlans)
      .finally(() => setLoadingPlans(false))
  }, [wsId])

  async function saveBrand(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId) return
    setSavingBrand(true)
    try {
      const saved = await upsertBrand(wsId, {
        name: brandForm.name,
        audience: brandForm.audience,
        tone: brandForm.tone,
        language: brandForm.language,
        avoid: brandForm.avoid.split(',').map(s => s.trim()).filter(Boolean),
      })
      setBrand(saved)
      setEditingBrand(false)
    } finally {
      setSavingBrand(false)
    }
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId) return
    setGenerating(true)
    setGenError('')
    try {
      const plan = await generatePlan(wsId, goal)
      navigate(`/workspaces/${wsId}/plans/${plan.id}`)
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Failed to start generation')
      setGenerating(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">M</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">Workspaces</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">Workspace</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* Brand Profile */}
        <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900">Brand Profile</h2>
            {brand && !editingBrand && (
              <button onClick={() => setEditingBrand(true)} className="text-sm text-indigo-600 hover:text-indigo-800">Edit</button>
            )}
          </div>
          <div className="p-6">
            {loadingBrand ? (
              <div className="text-gray-400 text-sm">Loading…</div>
            ) : editingBrand ? (
              <form onSubmit={saveBrand} className="space-y-4">
                {[
                  { label: 'Brand name', key: 'name', placeholder: 'e.g. Acme Corp' },
                  { label: 'Target audience', key: 'audience', placeholder: 'e.g. SMB owners in the US' },
                  { label: 'Tone', key: 'tone', placeholder: 'e.g. professional, friendly, bold' },
                  { label: 'Language', key: 'language', placeholder: 'en' },
                  { label: 'Words/topics to avoid', key: 'avoid', placeholder: 'competitors, politics (comma-separated)' },
                ].map(({ label, key, placeholder }) => (
                  <div key={key}>
                    <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
                    <input
                      type="text"
                      value={brandForm[key as keyof typeof brandForm]}
                      onChange={e => setBrandForm(f => ({ ...f, [key]: e.target.value }))}
                      placeholder={placeholder}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      required={key !== 'avoid'}
                    />
                  </div>
                ))}
                <div className="flex gap-2 pt-1">
                  <button type="submit" disabled={savingBrand} className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                    {savingBrand ? 'Saving…' : 'Save Brand'}
                  </button>
                  {brand && (
                    <button type="button" onClick={() => setEditingBrand(false)} className="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors">Cancel</button>
                  )}
                </div>
              </form>
            ) : brand ? (
              <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                {[
                  ['Name', brand.name],
                  ['Audience', brand.audience],
                  ['Tone', brand.tone],
                  ['Language', brand.language],
                  ['Avoid', (brand.avoid || []).join(', ') || '—'],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">{k}</dt>
                    <dd className="text-gray-900 mt-0.5">{v}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        </section>

        {/* Generate Plan */}
        {brand && (
          <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900">Generate Content Plan</h2>
              <p className="text-xs text-gray-500 mt-0.5">AI will create 7 posts for the week. You approve each one before anything is published.</p>
            </div>
            <div className="p-6">
              <form onSubmit={handleGenerate} className="flex gap-3">
                <input
                  type="text"
                  value={goal}
                  onChange={e => setGoal(e.target.value)}
                  placeholder="Optional goal, e.g. launch new product"
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <button
                  type="submit"
                  disabled={generating}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
                >
                  {generating ? 'Starting…' : 'Generate Plan'}
                </button>
              </form>
              {genError && <p className="text-red-600 text-xs mt-2">{genError}</p>}
            </div>
          </section>
        )}

        {/* Plans List */}
        <section>
          <h2 className="font-semibold text-gray-900 mb-3">Content Plans</h2>
          {loadingPlans ? (
            <div className="text-gray-400 text-sm">Loading…</div>
          ) : plans.length === 0 ? (
            <div className="text-center py-10 text-gray-400 bg-white border border-gray-200 rounded-xl">
              <p className="text-3xl mb-2">📅</p>
              <p className="text-sm">No plans yet. Generate your first one above.</p>
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
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[plan.status] ?? 'bg-gray-100 text-gray-600'}`}>
                            {plan.status}
                          </span>
                          <span className="text-xs text-gray-400">{new Date(plan.created_at).toLocaleDateString()}</span>
                        </div>
                        <p className="text-sm text-gray-700 truncate">{plan.goal || 'General brand awareness'}</p>
                        {plan.status === 'ready' && (
                          <p className="text-xs text-gray-400 mt-1">
                            {approved} approved · {pending} pending · {plan.posts.length} total
                          </p>
                        )}
                      </div>
                      <span className="text-gray-300 group-hover:text-indigo-400 text-xl ml-4">→</span>
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
