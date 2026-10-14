import type { ReactNode } from 'react'
import type {
  AnswerBlock,
  Basis,
  Block,
  BoardBlock,
  ComparisonBlock,
  Level,
  ListBlock,
  MatrixBlock,
  StatsBlock,
  TableBlock,
  TextBlock,
  TimelineBlock,
} from '../../../types'
import type { CitationRegistry } from '../citations'
import { SourceBadge } from '../SourceBadge'
import { ChartBlockView } from './ChartBlockView'
import { DiagramBlockView } from './DiagramBlockView'
import { Markdown } from './Markdown'
import { MatrixBlockView } from './MatrixBlockView'

// One renderer for every block type (app/schemas/blocks.py). Nothing here is
// specific to any analysis — a SWOT, a feasibility study and a persona study
// all render through these same components.

const BASIS_STYLE: Record<Basis, string> = {
  sourced: 'bg-emerald-50 text-emerald-700',
  calculated: 'bg-indigo-50 text-indigo-700',
  estimate: 'bg-amber-50 text-amber-700',
}
const BASIS_LABEL: Record<Basis, string> = { sourced: 'sourced', calculated: 'calculated', estimate: 'estimate' }

export function BasisPill({ basis }: { basis: Basis }) {
  return (
    <span className={`inline-block rounded-full px-1.5 py-px text-[10px] font-medium ${BASIS_STYLE[basis] ?? BASIS_STYLE.estimate}`}>
      {BASIS_LABEL[basis] ?? basis}
    </span>
  )
}

const LEVEL_STYLE: Record<Level, string> = {
  high: 'bg-indigo-100 text-indigo-700',
  medium: 'bg-sky-50 text-sky-700',
  low: 'bg-gray-100 text-gray-600',
}

function LevelPill({ level }: { level: Level }) {
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${LEVEL_STYLE[level]}`}>{level}</span>
}

const TEXT_KIND_LABEL: Record<TextBlock['kind'], string | null> = {
  reasoning: 'Reasoning',
  explanation: null,
  narrative: null,
  assumption: 'Assumption',
  note: null,
}

function AnswerView({ block }: { block: AnswerBlock }) {
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-base font-semibold text-gray-900">{block.headline}</p>
        <LevelPill level={block.confidence} />
      </div>
      {block.body && <Markdown text={block.body} className="mt-2 text-sm text-gray-700" />}
    </div>
  )
}

function TextView({ block }: { block: TextBlock }) {
  const label = TEXT_KIND_LABEL[block.kind]
  const tone =
    block.kind === 'reasoning'
      ? 'border-s-2 border-indigo-300 ps-3'
      : block.kind === 'assumption'
        ? 'border-s-2 border-amber-300 ps-3'
        : ''
  return (
    <div className={tone}>
      {label && <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>}
      <Markdown text={block.markdown} className="text-sm leading-relaxed text-gray-700" />
    </div>
  )
}

function StatsView({ block, compact }: { block: StatsBlock; compact: boolean }) {
  return (
    <div className={`grid gap-3 ${compact ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-3'}`}>
      {block.items.map((item, i) => (
        <div key={i} className="rounded-lg border border-gray-200 bg-white p-3">
          <p className="text-[11px] text-gray-500">{item.label}</p>
          <p className={`${compact ? 'text-base' : 'text-xl'} font-semibold text-gray-900`}>
            {item.value}
            {item.unit && <span className="ms-1 text-xs font-normal text-gray-500">{item.unit}</span>}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <BasisPill basis={item.basis} />
            {item.note && !compact && <span className="text-[11px] text-gray-500">{item.note}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

function TableView({ block }: { block: TableBlock }) {
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {block.columns.map((c, i) => (
                <th key={i} className="px-3 py-2 text-start text-xs font-semibold text-gray-600 whitespace-nowrap">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {block.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} className={`px-3 py-2 align-top text-gray-700 ${ci === 0 ? 'font-medium text-gray-900' : ''}`}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.caption && <p className="mt-1 text-[11px] text-gray-500">{block.caption}</p>}
    </div>
  )
}

function scoreColor(v: number | null): string {
  if (v === null) return 'bg-gray-50 text-gray-400'
  if (v >= 7.5) return 'bg-emerald-100 text-emerald-800'
  if (v >= 5) return 'bg-sky-50 text-sky-800'
  if (v >= 2.5) return 'bg-amber-50 text-amber-800'
  return 'bg-red-50 text-red-700'
}

function ComparisonView({ block }: { block: ComparisonBlock }) {
  const totals = block.scores.map((row) => {
    const vals = row.filter((v): v is number => v !== null)
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  })
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2" />
              {block.criteria.map((c, i) => (
                <th key={i} className="px-3 py-2 text-center text-xs font-semibold text-gray-600">{c}</th>
              ))}
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-600">Avg</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {block.options.map((opt, oi) => (
              <tr key={oi}>
                <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap">
                  {opt}
                  {block.notes[oi] && <p className="text-[11px] font-normal text-gray-500 whitespace-normal">{block.notes[oi]}</p>}
                </td>
                {block.scores[oi].map((v, ci) => (
                  <td key={ci} className="px-2 py-1.5 text-center">
                    <span className={`inline-block min-w-[2.5rem] rounded px-1.5 py-0.5 text-xs font-semibold ${scoreColor(v)}`}>
                      {v === null ? '—' : v.toFixed(v % 1 ? 1 : 0)}
                    </span>
                  </td>
                ))}
                <td className="px-2 py-1.5 text-center text-xs font-semibold text-gray-800">
                  {totals[oi] === null ? '—' : totals[oi]!.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-gray-400">Scores 0–10.</p>
      {block.verdict && <p className="text-sm font-medium text-gray-900">{block.verdict}</p>}
    </div>
  )
}

const CELL_TONES = ['border-emerald-200 bg-emerald-50/50', 'border-red-200 bg-red-50/40', 'border-sky-200 bg-sky-50/50', 'border-amber-200 bg-amber-50/50']

function BoardView({ block }: { block: BoardBlock }) {
  const cols = block.layout === 'columns' ? Math.min(block.cells.length, 4) : block.columns_count
  const gridCols = ['sm:grid-cols-1', 'sm:grid-cols-2', 'sm:grid-cols-3', 'sm:grid-cols-4'][Math.max(1, cols) - 1]
  // A 4-cell 2x2 grid reads as a SWOT-style board, so give each quadrant its own tone.
  const toned = block.cells.length === 4 && cols === 2
  return (
    <div className={`grid grid-cols-1 gap-3 ${gridCols}`}>
      {block.cells.map((cell, i) => (
        <div key={i} className={`rounded-lg border p-3 ${toned ? CELL_TONES[i] : 'border-gray-200 bg-white'}`}>
          <p className="text-sm font-semibold text-gray-900">{cell.title}</p>
          {cell.subtitle && <p className="text-[11px] text-gray-500">{cell.subtitle}</p>}
          <ul className="mt-2 space-y-1.5">
            {cell.items.map((item, j) => (
              <li key={j} className="text-sm text-gray-700">
                <span className="font-medium text-gray-900">{item.label}</span>
                {item.tag && <span className="ms-1.5 rounded bg-white/70 px-1 py-px text-[10px] text-gray-500 ring-1 ring-gray-200">{item.tag}</span>}
                {item.detail && <p className="text-xs text-gray-600">{item.detail}</p>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function TimelineView({ block }: { block: TimelineBlock }) {
  return (
    <ol className="relative space-y-4 border-s-2 border-indigo-100 ps-5">
      {block.phases.map((ph, i) => (
        <li key={i} className="relative">
          <span className="absolute -start-[27px] top-1 h-3 w-3 rounded-full border-2 border-white bg-indigo-500" />
          <p className="text-sm font-semibold text-gray-900">
            {ph.label}
            {(ph.start || ph.end) && (
              <span className="ms-2 text-xs font-normal text-gray-500">{[ph.start, ph.end].filter(Boolean).join(' – ')}</span>
            )}
          </p>
          {ph.items.length > 0 && (
            <ul className="mt-1 list-disc ps-5 text-sm text-gray-700 space-y-0.5">
              {ph.items.map((it, j) => (
                <li key={j}>{it}</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  )
}

function ListView({ block }: { block: ListBlock }) {
  const Tag = block.style === 'numbered' ? 'ol' : 'ul'
  return (
    <Tag className={`space-y-2 ${block.style === 'numbered' ? 'list-decimal ps-5' : ''}`}>
      {block.items.map((item, i) => (
        <li key={i} className={`text-sm text-gray-700 ${block.style === 'bullets' ? 'flex gap-2' : ''}`}>
          {block.style === 'bullets' && <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400" />}
          {block.style === 'checklist' && <span className="me-2 inline-block h-3.5 w-3.5 rounded border border-gray-300 align-middle" />}
          <span>
            <span className="font-medium text-gray-900">{item.label}</span>
            {item.rating && <span className="ms-2"><LevelPill level={item.rating} /></span>}
            {item.tag && <span className="ms-1.5 text-[11px] text-gray-500">#{item.tag}</span>}
            {item.detail && <span className="block text-gray-600">{item.detail}</span>}
          </span>
        </li>
      ))}
    </Tag>
  )
}

function body(block: Block, compact: boolean): ReactNode {
  switch (block.type) {
    case 'answer':
      return <AnswerView block={block} />
    case 'text':
      return <TextView block={block} />
    case 'stats':
      return <StatsView block={block} compact={compact} />
    case 'chart':
      return <ChartBlockView block={block} compact={compact} />
    case 'table':
      return <TableView block={block} />
    case 'comparison':
      return <ComparisonView block={block} />
    case 'board':
      return <BoardView block={block} />
    case 'matrix':
      return <MatrixBlockView block={block as MatrixBlock} compact={compact} />
    case 'diagram':
      return <DiagramBlockView block={block} />
    case 'timeline':
      return <TimelineView block={block} />
    case 'list':
      return <ListView block={block} />
    default:
      return null
  }
}

export function BlockRenderer({
  block,
  registry,
  anchorPrefix,
  compact = false,
}: {
  block: Block
  registry?: CitationRegistry
  anchorPrefix?: string
  compact?: boolean
}) {
  const content = body(block, compact)
  if (content === null) return null
  return (
    <div className="break-inside-avoid">
      {block.title && block.type !== 'answer' && (
        <p className="mb-2 text-sm font-semibold text-gray-800">
          {block.title}
          {block.type === 'chart' && <span className="ms-2 align-middle"><BasisPill basis={block.basis} /></span>}
          {registry && anchorPrefix && (
            <SourceBadge citations={block.citations} registry={registry} anchorPrefix={anchorPrefix} />
          )}
        </p>
      )}
      {content}
      {!block.title && registry && anchorPrefix && block.citations.length > 0 && (
        <p className="mt-1 text-[11px] text-gray-400">
          Sources <SourceBadge citations={block.citations} registry={registry} anchorPrefix={anchorPrefix} />
        </p>
      )}
    </div>
  )
}
