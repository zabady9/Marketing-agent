import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Funnel,
  FunnelChart,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import type { ChartBlock } from '../../../types'
import { COLORS, GRID_STROKE, AXIS_STROKE, AXIS_TICK } from './palette'

// Every chart type the engine can ask for (app/schemas/blocks.py CHART_TYPES).
// The backend already repaired series lengths, so this only reshapes data.
export function ChartBlockView({ block, compact = false }: { block: ChartBlock; compact?: boolean }) {
  const { categories, series } = block
  if (!categories?.length || !series?.length) {
    return <p className="text-xs text-gray-400">Chart data unavailable.</p>
  }

  const rows = categories.map((category, i) => {
    const row: Record<string, string | number | null> = { category }
    series.forEach((s) => {
      row[s.name] = s.data[i] ?? null
    })
    return row
  })
  const height = compact ? 170 : 280
  const tick = { fontSize: compact ? 9 : 11, fill: AXIS_TICK }
  const legend = series.length > 1 && !compact ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null
  const unitFmt = (v: unknown) => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString()}${block.unit ? ` ${block.unit}` : ''}`)
  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
      <XAxis dataKey="category" tick={tick} stroke={AXIS_STROKE} interval={0} angle={categories.length > 6 ? -25 : 0} textAnchor={categories.length > 6 ? 'end' : 'middle'} height={categories.length > 6 ? 50 : 30} />
      <YAxis tick={tick} stroke={AXIS_STROKE} width={compact ? 40 : 60} tickFormatter={(v) => Number(v).toLocaleString()} />
      <Tooltip formatter={(v) => unitFmt(v)} />
      {legend}
    </>
  )

  let chart
  switch (block.chart_type) {
    case 'line':
      chart = (
        <LineChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          {axes}
          {series.map((s, i) => (
            <Line key={s.name} type="monotone" dataKey={s.name} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={!compact} />
          ))}
        </LineChart>
      )
      break
    case 'area':
      chart = (
        <AreaChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          {axes}
          {series.map((s, i) => (
            <Area key={s.name} type="monotone" dataKey={s.name} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.2} />
          ))}
        </AreaChart>
      )
      break
    case 'stacked_bar':
    case 'bar':
      chart = (
        <BarChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          {axes}
          {series.map((s, i) => (
            <Bar
              key={s.name}
              dataKey={s.name}
              stackId={block.chart_type === 'stacked_bar' ? 'stack' : undefined}
              fill={COLORS[i % COLORS.length]}
              radius={block.chart_type === 'stacked_bar' ? 0 : [4, 4, 0, 0]}
              maxBarSize={40}
            />
          ))}
        </BarChart>
      )
      break
    case 'pie':
      chart = (
        <PieChart>
          <Tooltip formatter={(v) => unitFmt(v)} />
          <Pie data={rows} dataKey={series[0].name} nameKey="category" outerRadius={compact ? 55 : 95} label={!compact}>
            {rows.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          {!compact && <Legend wrapperStyle={{ fontSize: 11 }} />}
        </PieChart>
      )
      break
    case 'radar':
      chart = (
        <RadarChart data={rows} outerRadius={compact ? 55 : 95}>
          <PolarGrid stroke={GRID_STROKE} />
          <PolarAngleAxis dataKey="category" tick={{ fontSize: compact ? 8 : 10, fill: AXIS_TICK }} />
          <PolarRadiusAxis tick={{ fontSize: 9, fill: AXIS_TICK }} />
          <Tooltip />
          {series.map((s, i) => (
            <Radar key={s.name} dataKey={s.name} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.25} />
          ))}
          {legend}
        </RadarChart>
      )
      break
    case 'funnel':
      chart = (
        <FunnelChart>
          <Tooltip formatter={(v) => unitFmt(v)} />
          <Funnel
            dataKey="value"
            nameKey="name"
            data={categories.map((c, i) => ({ name: c, value: series[0].data[i] ?? 0, fill: COLORS[i % COLORS.length] }))}
            isAnimationActive={false}
          >
            {!compact && <LabelList position="right" dataKey="name" fill="#374151" stroke="none" fontSize={11} />}
          </Funnel>
        </FunnelChart>
      )
      break
    case 'scatter':
      // Categories are point labels; first series = x, second = y (or index).
      chart = (
        <ScatterChart margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
          <XAxis type="number" dataKey="x" name={block.x_label ?? series[0].name} tick={tick} stroke={AXIS_STROKE} />
          <YAxis type="number" dataKey="y" name={block.y_label ?? series[1]?.name ?? ''} tick={tick} stroke={AXIS_STROKE} />
          <ZAxis range={[60, 60]} />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} />
          <Scatter
            data={categories.map((c, i) => ({
              name: c,
              x: series[0].data[i] ?? 0,
              y: series[1] ? (series[1].data[i] ?? 0) : i,
            }))}
            fill={COLORS[0]}
          >
            {!compact && <LabelList dataKey="name" position="top" fontSize={10} fill="#374151" />}
          </Scatter>
        </ScatterChart>
      )
      break
  }

  return (
    <div dir="ltr">
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {chart}
        </ResponsiveContainer>
      </div>
      {!compact && (block.x_label || block.y_label) && block.chart_type !== 'scatter' && (
        <p className="mt-1 text-center text-[11px] text-gray-400">
          {[block.x_label, block.y_label].filter(Boolean).join(' · ')}
        </p>
      )}
    </div>
  )
}
