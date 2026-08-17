import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import type { VisualBlock, SourceRef } from '../types'

const COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#f59e0b',
  '#10b981', '#3b82f6', '#ef4444', '#14b8a6',
]

// ── outer container ───────────────────────────────────────────────────────────

interface Props {
  visuals: VisualBlock[]
  sources?: SourceRef[]
}

export default function VisualRenderer({ visuals, sources }: Props) {
  if (!visuals.length && (!sources || !sources.length)) return null
  return (
    <div className="mt-3 space-y-3">
      {visuals.map((block, i) => <VisualBlockCard key={i} block={block} />)}
      {sources && sources.length > 0 && <SourcesList sources={sources} />}
    </div>
  )
}

// ── per-block card ────────────────────────────────────────────────────────────

function VisualBlockCard({ block }: { block: VisualBlock }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 overflow-hidden">
      {block.title && (
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
          {block.title}
        </p>
      )}
      <BlockContent block={block} />
    </div>
  )
}

function BlockContent({ block }: { block: VisualBlock }) {
  switch (block.type) {
    case 'bar_chart':        return <BarChartBlock data={block.data} />
    case 'line_chart':       return <LineChartBlock data={block.data} />
    case 'area_chart':       return <AreaChartBlock data={block.data} />
    case 'table':            return <TableBlock data={block.data} />
    case 'metric_card':      return <MetricCardBlock data={block.data} />
    case 'radar_chart':      return <RadarChartBlock data={block.data} />
    case 'pie_chart':        return <PieChartBlock data={block.data} innerRadius={0} />
    case 'donut_chart':      return <PieChartBlock data={block.data} innerRadius={55} />
    case 'stacked_bar_chart': return <StackedBarChartBlock data={block.data} />
    case 'gauge':            return <GaugeBlock data={block.data} />
    case 'comparison_grid':  return <ComparisonGridBlock data={block.data} />
    case 'timeline':         return <TimelineBlock data={block.data} />
    case 'word_cloud':       return <WordCloudBlock data={block.data} />
    case 'progress_list':    return <ProgressListBlock data={block.data} />
    default:                 return null
  }
}

// ── bar chart ─────────────────────────────────────────────────────────────────

function BarChartBlock({ data }: { data: Record<string, unknown> }) {
  const items = Array.isArray(data.data) ? (data.data as Array<{ label: string; value: number }>).filter(Boolean) : []
  const rechartData = items.map(d => ({ name: d.label ?? '', value: d.value ?? 0 }))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={rechartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Bar dataKey="value" fill={COLORS[0]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── line chart ────────────────────────────────────────────────────────────────

function LineChartBlock({ data }: { data: Record<string, unknown> }) {
  const items = Array.isArray(data.data) ? (data.data as Array<{ label: string; value: number }>).filter(Boolean) : []
  const rechartData = items.map(d => ({ name: d.label ?? '', value: d.value ?? 0 }))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={rechartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Line type="monotone" dataKey="value" stroke={COLORS[0]} strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ── area chart ────────────────────────────────────────────────────────────────

function AreaChartBlock({ data }: { data: Record<string, unknown> }) {
  const items = Array.isArray(data.data) ? (data.data as Array<{ label: string; value: number }>).filter(Boolean) : []
  const rechartData = items.map(d => ({ name: d.label ?? '', value: d.value ?? 0 }))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={rechartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.2} />
            <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Area type="monotone" dataKey="value" stroke={COLORS[0]} fill="url(#areaGrad)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ── table ─────────────────────────────────────────────────────────────────────

function TableBlock({ data }: { data: Record<string, unknown> }) {
  const columns = Array.isArray(data.columns) ? (data.columns as string[]) : []
  const rows = Array.isArray(data.rows) ? (data.rows as string[][]) : []
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            {columns.map((col, i) => (
              <th key={i} className="border border-gray-200 bg-gray-50 px-3 py-1.5 text-right font-semibold text-gray-600">
                {col ?? ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? '' : 'bg-gray-50'}>
              {Array.isArray(row) ? row.map((cell, ci) => (
                <td key={ci} className="border border-gray-200 px-3 py-1.5 text-right text-gray-700">
                  {cell ?? ''}
                </td>
              )) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── metric card ───────────────────────────────────────────────────────────────

function MetricCardBlock({ data }: { data: Record<string, unknown> }) {
  const label = data.label as string ?? ''
  const value = data.value as string ?? ''
  const trend = data.trend as 'up' | 'down' | 'flat' | undefined
  const comparison = data.comparison as string | undefined

  const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'
  const trendColor = trend === 'up' ? 'text-emerald-500' : trend === 'down' ? 'text-red-500' : 'text-gray-400'

  return (
    <div className="flex items-center justify-between py-1">
      <div>
        <p className="text-xs text-gray-500">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
        {comparison && <p className="text-xs text-gray-400 mt-0.5">{comparison}</p>}
      </div>
      <span className={`text-3xl font-bold ${trendColor}`}>{trendIcon}</span>
    </div>
  )
}

// ── radar chart ───────────────────────────────────────────────────────────────

interface RadarSeriesItem { name: string; values: number[] }

function RadarChartBlock({ data }: { data: Record<string, unknown> }) {
  const axes = Array.isArray(data.axes) ? (data.axes as string[]) : []
  const series = Array.isArray(data.series) ? (data.series as RadarSeriesItem[]).filter(Boolean) : []

  const rechartData = axes.map((axis, i) => {
    const point: Record<string, unknown> = { subject: axis }
    series.forEach(s => { point[s.name] = Array.isArray(s.values) ? (s.values[i] ?? 0) : 0 })
    return point
  })

  return (
    <ResponsiveContainer width="100%" height={220}>
      <RadarChart data={rechartData}>
        <PolarGrid />
        <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11 }} />
        <PolarRadiusAxis tick={{ fontSize: 10 }} />
        {series.map((s, i) => (
          <Radar
            key={s.name}
            name={s.name}
            dataKey={s.name}
            stroke={COLORS[i % COLORS.length]}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.15}
          />
        ))}
        {series.length > 1 && <Legend />}
        <Tooltip />
      </RadarChart>
    </ResponsiveContainer>
  )
}

// ── pie / donut chart ─────────────────────────────────────────────────────────

function PieChartBlock({ data, innerRadius }: { data: Record<string, unknown>; innerRadius: number }) {
  const items = Array.isArray(data.data) ? (data.data as Array<{ label: string; value: number }>).filter(Boolean) : []
  const rechartData = items.map(d => ({ name: d.label ?? '', value: d.value ?? 0 }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={rechartData}
          cx="50%"
          cy="50%"
          innerRadius={innerRadius}
          outerRadius={80}
          dataKey="value"
          label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
          labelLine={false}
        >
          {rechartData.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  )
}

// ── stacked bar chart ─────────────────────────────────────────────────────────

interface StackedBarSeriesItem { name: string; values: number[] }

function StackedBarChartBlock({ data }: { data: Record<string, unknown> }) {
  const categories = Array.isArray(data.categories) ? (data.categories as string[]) : []
  const series = Array.isArray(data.series) ? (data.series as StackedBarSeriesItem[]).filter(Boolean) : []

  const rechartData = categories.map((cat, i) => {
    const point: Record<string, unknown> = { name: cat }
    series.forEach(s => { point[s.name] = Array.isArray(s.values) ? (s.values[i] ?? 0) : 0 })
    return point
  })

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={rechartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Legend />
        {series.map((s, i) => (
          <Bar key={s.name} dataKey={s.name} stackId="a" fill={COLORS[i % COLORS.length]} radius={i === series.length - 1 ? [4, 4, 0, 0] : undefined} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── gauge ─────────────────────────────────────────────────────────────────────

function GaugeBlock({ data }: { data: Record<string, unknown> }) {
  const label = data.label as string ?? ''
  const value = data.value as number ?? 0
  const min = data.min as number ?? 0
  const max = data.max as number ?? 100
  const target = data.target as number | undefined

  const pct = Math.min(1, Math.max(0, (value - min) / (max - min)))
  const rechartData = [{ name: label, value: Math.round(pct * 100), fill: COLORS[0] }]

  return (
    <div className="flex flex-col items-center">
      <ResponsiveContainer width="100%" height={140}>
        <RadialBarChart
          cx="50%"
          cy="70%"
          innerRadius="60%"
          outerRadius="80%"
          startAngle={180}
          endAngle={0}
          data={rechartData}
        >
          <RadialBar dataKey="value" cornerRadius={4} background={{ fill: '#f3f4f6' }} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="text-center -mt-6">
        <p className="text-2xl font-bold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
        {target !== undefined && (
          <p className="text-xs text-gray-400">target: {target}</p>
        )}
      </div>
    </div>
  )
}

// ── comparison grid ───────────────────────────────────────────────────────────

interface ComparisonGridItem {
  name: string
  highlight?: boolean
  metrics: Record<string, string>
}

function ComparisonGridBlock({ data }: { data: Record<string, unknown> }) {
  const items = (Array.isArray(data.items) ? (data.items as ComparisonGridItem[]) : []).filter(Boolean)
  if (!items.length) return null
  const metricKeys = Object.keys(items[0]?.metrics ?? {})

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {items.map((item, i) => (
        <div
          key={i}
          className={`rounded-lg border p-3 ${
            item.highlight
              ? 'border-indigo-400 bg-indigo-50'
              : 'border-gray-200 bg-gray-50'
          }`}
        >
          <p className={`text-xs font-semibold mb-2 truncate ${item.highlight ? 'text-indigo-700' : 'text-gray-700'}`}>
            {item.name}
            {item.highlight && <span className="ml-1 text-indigo-400">★</span>}
          </p>
          {metricKeys.map(key => (
            <div key={key} className="flex justify-between gap-1">
              <span className="text-xs text-gray-400 truncate">{key}</span>
              <span className="text-xs font-medium text-gray-700 shrink-0">{item.metrics[key]}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ── timeline ──────────────────────────────────────────────────────────────────

interface TimelineEvent { date: string; label: string }

function TimelineBlock({ data }: { data: Record<string, unknown> }) {
  const events = (Array.isArray(data.events) ? (data.events as TimelineEvent[]) : []).filter(Boolean)
  return (
    <ol className="relative border-r border-gray-200 mr-2 space-y-3 py-1">
      {events.map((ev, i) => (
        <li key={i} className="mr-4 relative">
          <span className="absolute -right-5 top-1 w-3 h-3 rounded-full bg-indigo-500 border-2 border-white ring-1 ring-indigo-200" />
          <p className="text-xs text-gray-400">{ev.date}</p>
          <p className="text-sm text-gray-700">{ev.label}</p>
        </li>
      ))}
    </ol>
  )
}

// ── word cloud ────────────────────────────────────────────────────────────────

interface WordEntry { text: string; weight: number }

function WordCloudBlock({ data }: { data: Record<string, unknown> }) {
  const words = (Array.isArray(data.words) ? (data.words as WordEntry[]) : []).filter(
    (w) => w && typeof w.text === 'string'
  )
  if (!words.length) return null

  const maxWeight = Math.max(...words.map((w) => w.weight ?? 1), 1)
  const minSize = 11
  const maxSize = 32

  return (
    <div className="flex flex-wrap gap-2 px-2 py-3 items-center justify-center">
      {words.map((w, i) => {
        const ratio = (w.weight ?? 1) / maxWeight
        const fontSize = Math.round(minSize + ratio * (maxSize - minSize))
        const color = COLORS[i % COLORS.length]
        return (
          <span
            key={i}
            style={{ fontSize, color, lineHeight: 1.3 }}
            className="font-medium transition-opacity hover:opacity-80"
          >
            {w.text}
          </span>
        )
      })}
    </div>
  )
}

// ── progress list ─────────────────────────────────────────────────────────────

interface ProgressItem { label: string; value: number; max: number }

function ProgressListBlock({ data }: { data: Record<string, unknown> }) {
  const items = (Array.isArray(data.items) ? (data.items as ProgressItem[]) : []).filter(Boolean)
  if (!items.length) return null

  return (
    <ul className="space-y-3 px-1">
      {items.map((item, i) => {
        const pct = Math.min(100, Math.round(((item.value ?? 0) / (item.max || 100)) * 100))
        const color = COLORS[i % COLORS.length]
        return (
          <li key={i}>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-700 font-medium">{item.label}</span>
              <span className="text-gray-500 tabular-nums">{item.value} / {item.max}</span>
            </div>
            <div className="h-2 w-full rounded-full bg-gray-100 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, backgroundColor: color }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// ── sources footnote ──────────────────────────────────────────────────────────

function SourcesList({ sources }: { sources: SourceRef[] }) {
  return (
    <div className="pt-1 border-t border-gray-100">
      <p className="text-xs text-gray-400 mb-1">المصادر</p>
      <ul className="space-y-0.5">
        {sources.map((s, i) => (
          <li key={i} className="text-xs">
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-500 hover:text-indigo-700 underline"
            >
              {s.title || s.url}
            </a>
            {s.fetched_at && (
              <span className="text-gray-400 mr-1"> · {s.fetched_at.slice(0, 10)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
