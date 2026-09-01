import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { EstimatedMarketFigure } from '../../../types'
import { formatCurrency, formatPercent } from '../../../lib/format'
import { JargonTerm } from '../JargonTerm'

// One hue, three shades — TAM/SAM/SOM is nested magnitude (each a subset of
// the last), not three unrelated categories, so this is a sequential ramp
// rather than a categorical palette. Matches the app's indigo accent.
const SHADES = ['#4338ca', '#6366f1', '#a5b4fc'] // indigo-700 / indigo-500 / indigo-300

function ratio(numerator: number | null, denominator: number | null): number | null {
  if (numerator === null || denominator === null || denominator === 0) return null
  return (numerator / denominator) * 100
}

export function TamSamSomChart({
  tam,
  sam,
  som,
  growthRateCagr,
  compact = false,
}: {
  tam: EstimatedMarketFigure
  sam: EstimatedMarketFigure
  som: EstimatedMarketFigure
  growthRateCagr: number | null
  compact?: boolean
}) {
  const currency = tam.currency || sam.currency || som.currency || 'USD'
  const data = [
    { name: 'TAM', value: tam.value ?? 0, hasValue: tam.value !== null },
    { name: 'SAM', value: sam.value ?? 0, hasValue: sam.value !== null },
    { name: 'SOM', value: som.value ?? 0, hasValue: som.value !== null },
  ]

  const samOverTam = ratio(sam.value, tam.value)
  const somOverSam = ratio(som.value, sam.value)

  return (
    <div>
      <div dir="ltr" className={compact ? 'h-[110px]' : 'h-[180px]'}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fontSize: compact ? 10 : 11, fill: '#898781' }}
              tickFormatter={(v: number) => formatCurrency(v, currency)}
              stroke="#c3c2b7"
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: compact ? 11 : 12, fill: '#52514e' }}
              width={40}
              stroke="#c3c2b7"
            />
            <Tooltip
              formatter={(value, _name, entry) =>
                (entry as { payload?: { hasValue?: boolean } })?.payload?.hasValue
                  ? formatCurrency(Number(value), currency)
                  : 'Unavailable'
              }
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={compact ? 20 : 28}>
              {data.map((entry, i) => (
                <Cell key={entry.name} fill={entry.hasValue ? SHADES[i] : '#e1e0d9'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
        <span>
          Growth (<JargonTerm term="CAGR">CAGR</JargonTerm>):{' '}
          <span className="font-semibold text-gray-900">
            {growthRateCagr === null ? '—' : formatPercent(growthRateCagr)}
          </span>
        </span>
        {!compact && (
          <>
            <span>
              SAM / TAM:{' '}
              <span className="font-semibold text-gray-900">
                {samOverTam === null ? '—' : formatPercent(samOverTam)}
              </span>
            </span>
            <span>
              SOM / SAM:{' '}
              <span className="font-semibold text-gray-900">
                {somOverSam === null ? '—' : formatPercent(somOverSam)}
              </span>
            </span>
          </>
        )}
      </div>
    </div>
  )
}
