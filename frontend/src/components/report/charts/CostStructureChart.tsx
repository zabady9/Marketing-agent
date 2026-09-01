import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CostStructureValue } from '../../../types'
import { formatCurrency } from '../../../lib/format'

const COLORS = ['#4f46e5', '#0891b2'] // indigo-600 (one-time), cyan-600 (recurring)

export function CostStructureChart({
  value,
  currency,
  compact = false,
}: {
  value: CostStructureValue
  currency: string
  compact?: boolean
}) {
  const years = value.horizon_months / 12
  const data = [
    { label: 'Capex (one-time)', amount: value.capex },
    { label: `Opex (${years % 1 === 0 ? years : years.toFixed(1)}y cumulative)`, amount: value.cumulative_opex },
  ]

  return (
    <div>
      <div dir="ltr" className={compact ? 'h-[80px]' : 'h-[120px]'}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fontSize: 10, fill: '#898781' }}
              tickFormatter={(v: number) => formatCurrency(v, currency, 0)}
              stroke="#c3c2b7"
            />
            <YAxis
              type="category"
              dataKey="label"
              tick={{ fontSize: compact ? 9 : 11, fill: '#52514e' }}
              width={compact ? 90 : 120}
              stroke="#c3c2b7"
            />
            <Tooltip formatter={(v) => formatCurrency(Number(v), currency)} />
            <Bar dataKey="amount" radius={[0, 4, 4, 0]} maxBarSize={compact ? 14 : 20}>
              {data.map((d, i) => (
                <Cell key={d.label} fill={COLORS[i]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {!compact && (
        <p className="mt-1 text-[11px] text-gray-400">
          Total over the horizon: {formatCurrency(value.total_cost, currency)}
        </p>
      )}
    </div>
  )
}
