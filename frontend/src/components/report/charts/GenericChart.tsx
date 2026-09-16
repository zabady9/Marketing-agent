import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PieLabelRenderProps } from 'recharts'
import type { ChartSpec } from '../../../types'

// Same categorical palette as RiskCategoryChart/CompetitorPositionChart —
// distinct hues for unrelated series/categories, not a sequential magnitude
// ramp like TamSamSomChart's SHADES (a generate_chart_tool spec has no
// inherent nesting relationship between its series/categories, so a
// categorical palette is the right default here).
const CATEGORY_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#4a3aa7', '#008300']

const GRID_STROKE = '#e1e0d9'
const AXIS_STROKE = '#c3c2b7'
const AXIS_TICK_FILL = '#898781'

// Renders a chat agent's generate_chart_tool result (see
// app/schemas/chart.py::ChartSpec) directly — bar/line get one Bar/Line per
// series with `categories` as the shared X-axis; pie takes its single
// series' values as the slice values. Reuses the same axis/grid/tooltip
// styling as the other report charts rather than inventing a new visual
// language; unlike those (which each render one fixed, known dataset), this
// one's categories/series count is arbitrary, so it uses a categorical
// palette cycled by index instead of a fixed per-field color mapping.
//
// The card-level title (chart.title) is intentionally NOT rendered here —
// matching every other chart component in this directory, which never
// self-title; that's the wrapping SectionCardShell's job (see ChatPage.tsx).
export function GenericChart({ chart, compact = false }: { chart: ChartSpec; compact?: boolean }) {
  if (
    !chart ||
    !Array.isArray(chart.categories) ||
    chart.categories.length === 0 ||
    !Array.isArray(chart.series) ||
    chart.series.length === 0
  ) {
    // Malformed/missing spec — never crash, just skip the chart.
    return <p className="text-xs text-gray-400">Chart data unavailable.</p>
  }

  // Pivot the categories+series shape into recharts' preferred one-row-per-
  // category shape, keyed by series name. Null values pass through as-is —
  // recharts treats a null datum as a gap (Line supports this natively via
  // connectNulls; Bar simply omits that bar) rather than erroring.
  const data = chart.categories.map((category, i) => {
    const row: Record<string, string | number | null> = { category }
    chart.series.forEach((s) => {
      row[s.name] = s.data[i] ?? null
    })
    return row
  })

  const showLegend = chart.series.length > 1 && !compact
  const xTick = { fontSize: compact ? 9 : 10, fill: AXIS_TICK_FILL }
  const yTick = { fontSize: compact ? 9 : 10, fill: AXIS_TICK_FILL }
  const xAxisLabel =
    !compact && chart.x_label
      ? { value: chart.x_label, position: 'insideBottom' as const, offset: -6, fontSize: 10, fill: AXIS_TICK_FILL }
      : undefined
  const yAxisLabel =
    !compact && chart.y_label
      ? { value: chart.y_label, angle: -90, position: 'insideLeft' as const, fontSize: 10, fill: AXIS_TICK_FILL }
      : undefined
  const bottomMargin = !compact && chart.x_label ? 20 : compact ? 4 : 8

  return (
    <div dir="ltr" className={compact ? 'h-[150px]' : 'h-[240px]'}>
      <ResponsiveContainer width="100%" height="100%">
        {chart.chart_type === 'pie' ? (
          <PieChart margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
            <Tooltip formatter={(value) => [String(value), chart.series[0].name]} />
            <Pie
              data={data}
              dataKey={chart.series[0].name}
              nameKey="category"
              cx="50%"
              cy="50%"
              outerRadius={compact ? 50 : 85}
              label={compact ? false : (props: PieLabelRenderProps) => props.name}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
              ))}
            </Pie>
            {showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
          </PieChart>
        ) : chart.chart_type === 'line' ? (
          <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: bottomMargin }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            <XAxis dataKey="category" tick={xTick} stroke={AXIS_STROKE} label={xAxisLabel} />
            <YAxis tick={yTick} stroke={AXIS_STROKE} width={compact ? 40 : 56} label={yAxisLabel} />
            <Tooltip />
            {showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {chart.series.map((s, i) => (
              <Line
                key={s.name}
                type="monotone"
                dataKey={s.name}
                stroke={CATEGORY_COLORS[i % CATEGORY_COLORS.length]}
                strokeWidth={2}
                dot={compact ? false : { r: 3 }}
                connectNulls={false}
              />
            ))}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: bottomMargin }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="category" tick={xTick} stroke={AXIS_STROKE} label={xAxisLabel} />
            <YAxis tick={yTick} stroke={AXIS_STROKE} width={compact ? 40 : 56} label={yAxisLabel} />
            <Tooltip />
            {showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {chart.series.map((s, i) => (
              <Bar
                key={s.name}
                dataKey={s.name}
                fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]}
                radius={[4, 4, 0, 0]}
                maxBarSize={compact ? 24 : 36}
              />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
