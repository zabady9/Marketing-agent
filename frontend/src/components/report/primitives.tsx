import type { ReactNode } from 'react'
import { JargonTerm } from './JargonTerm'

// Shared visual language between the in-chat SectionCard summaries and the
// full Study Report page — extracted out of ChatPage so both surfaces stay
// visually consistent instead of duplicating markup.

export function SectionCardShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 px-4 py-3 max-w-md">
      <p className="text-xs font-semibold text-indigo-700 mb-2">{title}</p>
      {children}
    </div>
  )
}

export function Stat({
  label,
  term,
  value,
  unit,
}: {
  label: string
  // Glossary term this label maps to (e.g. "ROI" for label="ROI Year 1"),
  // when it differs from `label` itself. Omit when label === term.
  term?: string
  value: string
  unit?: string
}) {
  const labelNode = term ? <JargonTerm term={term}>{label}</JargonTerm> : label
  return (
    <div>
      <p className="text-sm font-semibold text-gray-900">{value}</p>
      <p className="text-[10px] text-gray-500">
        {labelNode}
        {unit ? ` (${unit})` : ''}
      </p>
    </div>
  )
}
