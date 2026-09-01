import type { ConfidenceBreakdown } from '../../../types'
import { formatPercent } from '../../../lib/format'

// Fixed weights the confidence_score is composed from (app/tools/confidence.py) —
// not part of the payload, so hard-coded here per the report spec.
const WEIGHTS: { key: keyof ConfidenceBreakdown; label: string; weight: number; color: string }[] = [
  { key: 'citation_score', label: 'Citations', weight: 0.4, color: '#4f46e5' }, // indigo-600
  { key: 'risk_score', label: 'Risk', weight: 0.3, color: '#0891b2' }, // cyan-600
  { key: 'completeness_score', label: 'Completeness', weight: 0.2, color: '#059669' }, // emerald-600
  { key: 'pipeline_score', label: 'Pipeline health', weight: 0.1, color: '#d97706' }, // amber-600
]

function heroColor(score: number): string {
  if (score >= 0.7) return 'text-emerald-600'
  if (score >= 0.4) return 'text-amber-600'
  return 'text-red-600'
}

function heroBarColor(score: number): string {
  if (score >= 0.7) return 'bg-emerald-500'
  if (score >= 0.4) return 'bg-amber-500'
  return 'bg-red-500'
}

// Plain-HTML weighted stacked bar (segment width = weight × sub-score, out of
// a 100%-weight total) plus a hero meter for the overall score. Built as
// direct divs rather than a Recharts chart — it's a fixed-weight proportion
// readout with direct labels, not plottable series data, and divs print
// cleanly with no extra work.
export function ConfidenceMeter({
  confidenceScore,
  breakdown,
  compact = false,
}: {
  confidenceScore: number
  breakdown: ConfidenceBreakdown
  compact?: boolean
}) {
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <p className={`${compact ? 'text-2xl' : 'text-4xl'} font-bold tabular-nums ${heroColor(confidenceScore)}`}>
          {formatPercent(confidenceScore * 100, 0)}
        </p>
        <p className="text-sm text-gray-500">overall confidence</p>
      </div>
      <div className="mt-1.5 h-2.5 w-full rounded-full bg-gray-100">
        <div
          className={`h-2.5 rounded-full ${heroBarColor(confidenceScore)}`}
          style={{ width: `${Math.max(0, Math.min(1, confidenceScore)) * 100}%` }}
        />
      </div>

      {!compact && (
        <>
          <p className="mt-4 mb-1.5 text-xs font-medium text-gray-500">
            Weighted composition (citations 40% · risk 30% · completeness 20% · pipeline 10%)
          </p>
          <div className="flex h-7 w-full overflow-hidden rounded-md border border-gray-200" dir="ltr">
            {WEIGHTS.map(({ key, label, weight, color }) => {
              const subScore = Math.max(0, Math.min(1, breakdown[key] ?? 0))
              const segmentWidth = weight * subScore * 100
              return (
                <div
                  key={key}
                  className="flex h-full items-center justify-center overflow-hidden text-[10px] font-medium text-white transition-all"
                  style={{ width: `${segmentWidth}%`, backgroundColor: color }}
                  title={`${label}: ${formatPercent(subScore * 100, 0)} (weight ${formatPercent(weight * 100, 0)})`}
                >
                  {segmentWidth > 8 ? formatPercent(subScore * 100, 0) : ''}
                </div>
              )
            })}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
            {WEIGHTS.map(({ key, label, color }) => (
              <span key={key} className="flex items-center gap-1 text-[11px] text-gray-500">
                <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
                {label}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
