import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CompetitorProfile, MarketPosition } from '../../../types'

// Same color mapping as CompetitiveLandscapeSection's table pills (indigo/
// blue/teal/gray), so the chart and table read as one consistent system.
const POSITION_ORDER: MarketPosition[] = ['leader', 'challenger', 'niche', 'unknown']
const POSITION_COLOR: Record<MarketPosition, string> = {
  leader: '#4f46e5', // indigo-600
  challenger: '#2563eb', // blue-600
  niche: '#0d9488', // teal-600
  unknown: '#9ca3af', // gray-400
}
const POSITION_LABEL: Record<MarketPosition, string> = {
  leader: 'Leader',
  challenger: 'Challenger',
  niche: 'Niche',
  unknown: 'Unknown',
}

export function CompetitorPositionChart({
  competitors,
  compact = false,
}: {
  competitors: CompetitorProfile[]
  compact?: boolean
}) {
  const data = POSITION_ORDER.map((position) => ({
    position,
    label: POSITION_LABEL[position],
    count: competitors.filter((c) => c.market_position === position).length,
  })).filter((d) => d.count > 0 || !compact) // compact: skip empty buckets to save space

  if (data.length === 0) return null

  return (
    <div dir="ltr" className={compact ? 'h-[90px]' : 'h-[140px]'}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: '#898781' }} stroke="#c3c2b7" />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fontSize: compact ? 10 : 11, fill: '#52514e' }}
            width={compact ? 64 : 76}
            stroke="#c3c2b7"
          />
          <Tooltip formatter={(value) => [`${value}`, 'Competitors']} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={compact ? 14 : 20}>
            {data.map((d) => (
              <Cell key={d.position} fill={POSITION_COLOR[d.position]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
