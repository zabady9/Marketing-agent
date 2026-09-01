import { useEffect, useState, type FormEvent } from 'react'
import { getAdminBusinessProfile } from '../../../adminApi'
import type { ProjectAdminResponse } from '../../../adminTypes'
import type { BusinessProfile } from '../../../types'
import type { AdminFormProps } from '../AdminEntityPage'

// Project has no independent create endpoint (every project needs a
// BusinessProfile, created only via the wizard) — this form is edit-only in
// practice, but keeps the standard {mode, initial, onSubmit, onCancel} shape.
export function ProjectForm({ mode, initial, onSubmit, onCancel }: AdminFormProps<ProjectAdminResponse>) {
  const [name, setName] = useState(initial?.name ?? '')
  const [status, setStatus] = useState(initial?.status ?? '')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [profile, setProfile] = useState<BusinessProfile | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)

  useEffect(() => {
    if (mode !== 'edit' || !initial) return
    let cancelled = false
    getAdminBusinessProfile(initial.id)
      .then((data) => {
        if (!cancelled) setProfile(data)
      })
      .catch((err) => {
        if (!cancelled) setProfileError(err instanceof Error ? err.message : 'Failed to load business profile.')
      })
    return () => {
      cancelled = true
    }
  }, [mode, initial])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      await onSubmit({ name, status })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Status</label>
        <input
          type="text"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
        />
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSubmitting}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {isSubmitting ? 'Saving…' : 'Save'}
        </button>
      </div>

      {mode === 'edit' && (
        <div className="mt-6 border-t border-gray-200 pt-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-900">Business Profile (read-only)</h3>
          <p className="mb-3 text-xs text-gray-500">
            Edit this via the project's own business profile page — not duplicated here.
          </p>
          {profileError && <p className="text-sm text-red-600">{profileError}</p>}
          {!profile && !profileError && <p className="text-sm text-gray-400">Loading…</p>}
          {profile && (
            <dl className="max-h-64 space-y-2 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs">
              <Row label="Business description" value={profile.business_description.value} />
              <Row label="Problem statement" value={profile.problem_statement.value} />
              <Row label="Unique value proposition" value={profile.unique_value_proposition.value} />
              <Row label="Target market" value={profile.target_market_description.value} />
              <Row label="Geography" value={profile.target_market_geography.value} />
              <Row label="Business model" value={profile.business_model_type.value} />
              <Row label="Capex" value={`${profile.capex.value} ${profile.capex_currency}`} />
              <Row label="Opex / mo" value={`${profile.opex_monthly.value} ${profile.opex_monthly_currency}`} />
              <Row label="Pricing" value={`${profile.pricing_unit_price.value} ${profile.pricing_currency}`} />
              <Row label="Team size" value={profile.team_size?.value ?? '—'} />
              <Row label="Competitors" value={profile.competitors.map((c) => c.name).join(', ') || '—'} />
            </dl>
          )}
        </div>
      )}
    </form>
  )
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 font-medium text-gray-500">{label}</dt>
      <dd className="truncate text-right text-gray-800">{String(value)}</dd>
    </div>
  )
}
