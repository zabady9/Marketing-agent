import type { ClaimType } from '../../types'

const LABELS: Record<ClaimType, string> = {
  verified_fact: 'Verified',
  assumption: 'Assumption',
  calculated_estimate: 'Calculated',
  forecast: 'Forecast',
  opinion: 'Opinion',
  unavailable: 'Unavailable',
}

const CLASSES: Record<ClaimType, string> = {
  verified_fact: 'bg-emerald-100 text-emerald-700',
  assumption: 'bg-gray-100 text-gray-600',
  calculated_estimate: 'bg-blue-100 text-blue-700',
  forecast: 'bg-violet-100 text-violet-700',
  opinion: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-red-100 text-red-600',
}

export const CLAIM_TYPE_DESCRIPTIONS: Record<ClaimType, string> = {
  verified_fact: 'Backed by a resolved citation/URL.',
  assumption: 'A user- or system-assumed input, not measured.',
  calculated_estimate: 'Deterministic math — see the calculation trace.',
  forecast: 'A projection or extrapolation (e.g. CAGR).',
  opinion: "The AI's qualitative judgment or recommendation.",
  unavailable: 'Explicit no-data marker — never a guess.',
}

// Small colored pill keyed on claim_type. Renders nothing if claim_type is
// absent, so callers can pass it through unconditionally.
export function ClassificationBadge({ claimType }: { claimType?: ClaimType | null }) {
  if (!claimType) return null
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap ${CLASSES[claimType]}`}
    >
      {LABELS[claimType]}
    </span>
  )
}

const ALL_CLAIM_TYPES: ClaimType[] = [
  'verified_fact',
  'assumption',
  'calculated_estimate',
  'forecast',
  'opinion',
  'unavailable',
]

// Renders once in the Methodology & Sources appendix — explains what each
// classification pill means, rather than repeating the legend per section.
export function ClassificationLegend() {
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {ALL_CLAIM_TYPES.map((claimType) => (
        <div key={claimType} className="flex items-start gap-2">
          <dt>
            <ClassificationBadge claimType={claimType} />
          </dt>
          <dd className="text-xs text-gray-600">{CLAIM_TYPE_DESCRIPTIONS[claimType]}</dd>
        </div>
      ))}
    </dl>
  )
}
