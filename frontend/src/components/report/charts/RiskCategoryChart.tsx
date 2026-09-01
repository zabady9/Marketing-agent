import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { RiskEntry } from '../../../types'

// Matches app/schemas/risk.py::RiskCategory's declared order. Any category
// value not in this list (shouldn't happen, but risk.category is a plain
// string on the frontend, not a strict union) is appended at the end rather
// than silently dropped.
const KNOWN_CATEGORY_ORDER = [
  'market',
  'financial',
  'operational',
  'regulatory',
  'competitive',
  'technology',
]

// Categorical palette (distinct hues — these are unrelated risk types, not a
// nested/sequential magnitude like TAM/SAM/SOM).
const CATEGORY_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#4a3aa7', '#008300']

function categoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1)
}

export function RiskCategoryChart({ risks, compact = false }: { risks: RiskEntry[]; compact?: boolean }) {
  const counts = new Map<string, number>()
  for (const r of risks) {
    counts.set(r.category, (counts.get(r.category) ?? 0) + 1)
  }

  const orderedCategories = [
    ...KNOWN_CATEGORY_ORDER.filter((c) => counts.has(c)),
    ...[...counts.keys()].filter((c) => !KNOWN_CATEGORY_ORDER.includes(c)),
  ]
  const data = orderedCategories.map((category) => ({
    category,
    label: categoryLabel(category),
    count: counts.get(category) ?? 0,
  }))

  if (data.length === 0) return null

  return (
    <div dir="ltr" className={compact ? 'h-[110px]' : 'h-[170px]'}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: '#898781' }} stroke="#c3c2b7" />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fontSize: compact ? 10 : 11, fill: '#52514e' }}
            width={compact ? 70 : 82}
            stroke="#c3c2b7"
          />
          <Tooltip formatter={(value) => [`${value}`, 'Risks']} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={compact ? 14 : 18}>
            {data.map((d, i) => (
              <Cell key={d.category} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
