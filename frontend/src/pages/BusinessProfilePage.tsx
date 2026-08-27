import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getBusinessProfile } from '../api'
import type { BusinessProfile } from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

function SourceBadge({ source, lowConfidence }: { source: string; lowConfidence?: boolean }) {
  const isEstimated = source === 'estimated'
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap ${
        isEstimated ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'
      }`}
    >
      {isEstimated ? 'estimated' : 'user provided'}
      {lowConfidence ? ' · low confidence' : ''}
    </span>
  )
}

function Field({
  label,
  value,
  source,
  lowConfidence,
}: {
  label: string
  value: ReactNode
  source?: string
  lowConfidence?: boolean
}) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <p className="text-xs font-medium text-gray-500">{label}</p>
        {source && <SourceBadge source={source} lowConfidence={lowConfidence} />}
      </div>
      <p className="mt-0.5 text-sm text-gray-900">{value}</p>
    </div>
  )
}

export function BusinessProfilePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [profile, setProfile] = useState<BusinessProfile | null>(null)
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    setState('loading')
    getBusinessProfile(projectId)
      .then((data) => {
        if (cancelled) return
        setProfile(data)
        setState('loaded')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load business profile.')
        setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500 text-sm">Loading business profile…</p>
      </div>
    )
  }

  if (state === 'error' || !profile) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4 px-4">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 max-w-md text-center">
          {error ?? 'Business profile not found.'}
        </div>
        <Link to="/" className="text-sm text-indigo-600 hover:text-indigo-700 font-medium">
          ← Back to projects
        </Link>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-2">
          <Link to="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Projects
          </Link>
          <Link
            to={`/projects/${projectId}/chat`}
            className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
          >
            Chat about this project →
          </Link>
        </div>

        <h1 className="text-3xl font-semibold text-gray-900 tracking-tight mb-1">
          Business Profile
        </h1>
        <p className="text-sm text-gray-400 mb-8">Extracted from your questionnaire answers.</p>

        <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-6">
          <Field
            label="Business description"
            value={profile.business_description.value}
            source={profile.business_description.source}
            lowConfidence={profile.business_description.low_confidence}
          />

          <div className="grid grid-cols-2 gap-6">
            <Field
              label="Problem being solved"
              value={profile.problem_statement.value || '—'}
              source={profile.problem_statement.source}
            />
            <Field
              label="Unique value proposition"
              value={profile.unique_value_proposition.value || '—'}
              source={profile.unique_value_proposition.source}
            />
            <Field
              label="Target market"
              value={profile.target_market_description.value || '—'}
              source={profile.target_market_description.source}
              lowConfidence={profile.target_market_description.low_confidence}
            />
            <Field
              label="Geography"
              value={profile.target_market_geography.value || '—'}
              source={profile.target_market_geography.source}
              lowConfidence={profile.target_market_geography.low_confidence}
            />
            <Field
              label="Target market type"
              value={profile.target_market_type.value || '—'}
              source={profile.target_market_type.source}
            />
            <Field
              label="Business model"
              value={profile.business_model_type.value || '—'}
              source={profile.business_model_type.source}
              lowConfidence={profile.business_model_type.low_confidence}
            />
            <Field
              label="Pricing"
              value={`${profile.pricing_unit_price.value} ${profile.pricing_currency}${
                profile.pricing_model.value ? ` (${profile.pricing_model.value})` : ''
              }`}
              source={profile.pricing_unit_price.source}
            />
            <Field
              label="Expected monthly sales"
              value={profile.expected_monthly_sales.value ?? '—'}
              source={profile.expected_monthly_sales.source}
              lowConfidence={profile.expected_monthly_sales.low_confidence}
            />
            <Field
              label="Capex"
              value={`${profile.capex.value} ${profile.capex_currency}`}
              source={profile.capex.source}
              lowConfidence={profile.capex.low_confidence}
            />
            <Field
              label="Monthly opex"
              value={`${profile.opex_monthly.value} ${profile.opex_monthly_currency}`}
              source={profile.opex_monthly.source}
              lowConfidence={profile.opex_monthly.low_confidence}
            />
            <Field
              label="Funding source"
              value={profile.funding_source.value || '—'}
              source={profile.funding_source.source}
            />
            <Field
              label="Team size"
              value={profile.team_size ? profile.team_size.value : 'Not specified'}
              source={profile.team_size?.source}
              lowConfidence={profile.team_size?.low_confidence}
            />
            <Field
              label="Study goal"
              value={profile.study_goal.value || '—'}
              source={profile.study_goal.source}
            />
            <Field label="Analysis horizon" value={`${profile.analysis_horizon_years} years`} />
          </div>

          <div>
            <div className="flex items-center gap-2 mb-2">
              <p className="text-xs font-medium text-gray-500">Competitors</p>
            </div>
            {profile.competitors.length === 0 ? (
              <p className="text-sm text-gray-400">None listed</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {profile.competitors.map((c) => (
                  <span
                    key={c.name}
                    className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700"
                  >
                    {c.name}
                    <SourceBadge source={c.source} />
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center gap-2 mb-2">
              <p className="text-xs font-medium text-gray-500">Key roles needed</p>
              <SourceBadge source={profile.key_roles_needed.source} />
            </div>
            {profile.key_roles_needed.value.length === 0 ? (
              <p className="text-sm text-gray-400">None listed</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {profile.key_roles_needed.value.map((role) => (
                  <span
                    key={role}
                    className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700"
                  >
                    {role}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center gap-2 mb-2">
              <p className="text-xs font-medium text-gray-500">Sales / marketing channels</p>
              <SourceBadge source={profile.marketing_channels.source} />
            </div>
            {profile.marketing_channels.value.length === 0 ? (
              <p className="text-sm text-gray-400">None listed</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {profile.marketing_channels.value.map((channel) => (
                  <span
                    key={channel}
                    className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700"
                  >
                    {channel}
                  </span>
                ))}
              </div>
            )}
          </div>

          <Field
            label="Founder-stated risks"
            value={profile.founder_risks.value || 'None stated'}
            source={profile.founder_risks.source}
          />
        </div>
      </div>
    </div>
  )
}
