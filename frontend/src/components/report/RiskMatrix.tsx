import { Fragment } from 'react'
import type { RiskEntry, RiskLevel } from '../../types'

const LEVELS: RiskLevel[] = ['low', 'medium', 'high']
const RANK: Record<RiskLevel, number> = { low: 1, medium: 2, high: 3 }

function severityClasses(probability: RiskLevel, impact: RiskLevel): string {
  const score = RANK[probability] * RANK[impact]
  if (score >= 6) return 'bg-red-50 border-red-200'
  if (score >= 3) return 'bg-amber-50 border-amber-200'
  return 'bg-emerald-50 border-emerald-200'
}

function chipClasses(probability: RiskLevel, impact: RiskLevel): string {
  const score = RANK[probability] * RANK[impact]
  if (score >= 6) return 'bg-red-100 text-red-800 hover:bg-red-200'
  if (score >= 3) return 'bg-amber-100 text-amber-800 hover:bg-amber-200'
  return 'bg-emerald-100 text-emerald-800 hover:bg-emerald-200'
}

function shortLabel(text: string, max = 36): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

// Hand-rolled 3x3 probability x impact grid — a fixed categorical layout with
// derived severity, not continuous data, so this is plain CSS grid rather
// than a Recharts scatter. Genuinely mirrors under the page's real `dir`
// (CSS grid flow respects writing direction) — unlike the Recharts charts,
// which don't, so this one is deliberately left to inherit `dir` rather than
// being pinned to ltr.
export function RiskMatrix({
  risks,
  onSelectRisk,
  compact = false,
}: {
  risks: RiskEntry[]
  // Optional — chat's compact card has no full risk table below it to jump
  // to, so chips there are just labeled (non-interactive) severity markers.
  onSelectRisk?: (index: number) => void
  compact?: boolean
}) {
  const cells = new Map<string, { risk: RiskEntry; index: number }[]>()
  risks.forEach((risk, index) => {
    const key = `${risk.probability}:${risk.impact}`
    const bucket = cells.get(key) ?? []
    bucket.push({ risk, index })
    cells.set(key, bucket)
  })

  return (
    <div>
      <div className={`grid grid-cols-[auto_repeat(3,1fr)] ${compact ? 'gap-1 text-[10px]' : 'gap-1.5 text-xs'}`}>
        <div />
        {LEVELS.map((impact) => (
          <div key={impact} className="text-center font-medium text-gray-500 capitalize pb-1">
            {impact}{!compact && ' impact'}
          </div>
        ))}
        {[...LEVELS].reverse().map((probability) => (
          <Fragment key={probability}>
            <div className="flex items-center justify-end pe-2 font-medium text-gray-500 capitalize">
              {probability}
            </div>
            {LEVELS.map((impact) => {
              const bucket = cells.get(`${probability}:${impact}`) ?? []
              return (
                <div
                  key={`${probability}:${impact}`}
                  className={`${compact ? 'min-h-[40px] p-1' : 'min-h-[72px] p-1.5'} rounded-lg border flex flex-wrap content-start gap-1 ${severityClasses(probability, impact)}`}
                >
                  {bucket.map(({ risk, index }) =>
                    onSelectRisk ? (
                      <button
                        key={index}
                        type="button"
                        onClick={() => onSelectRisk(index)}
                        title={risk.risk_description}
                        className={`rounded-md px-1.5 py-1 text-start text-[11px] font-medium transition-colors ${chipClasses(probability, impact)}`}
                      >
                        {shortLabel(risk.risk_description, compact ? 20 : 36)}
                      </button>
                    ) : (
                      <span
                        key={index}
                        title={risk.risk_description}
                        className={`rounded-md px-1.5 py-1 text-start text-[11px] font-medium ${chipClasses(probability, impact)}`}
                      >
                        {shortLabel(risk.risk_description, compact ? 20 : 36)}
                      </span>
                    ),
                  )}
                </div>
              )
            })}
          </Fragment>
        ))}
      </div>
      {!compact && (
        <p className="mt-2 text-[11px] text-gray-400">
          Rows: probability (high → low, top to bottom). Columns: impact (low → high). Click a risk
          to jump to its row in the table below.
        </p>
      )}
    </div>
  )
}
