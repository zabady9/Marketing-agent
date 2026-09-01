import type { Citation } from '../../types'
import type { CitationRegistry } from './citations'

// Numbered footnote marker next to a claim/figure/entity that has citations —
// e.g. "[1,2]" linking down to that section's CitationFootnotes list.
// Renders nothing when there are no citations, or none resolve in the
// registry (shouldn't happen in practice, but never crash either way).
export function SourceBadge({
  citations,
  registry,
  anchorPrefix,
}: {
  citations: Citation[] | undefined
  registry: CitationRegistry
  anchorPrefix: string
}) {
  if (!citations || citations.length === 0) return null

  const numbers = Array.from(
    new Set(
      citations
        .map((c) => registry.indexOf(c.url))
        .filter((n): n is number => n !== undefined),
    ),
  ).sort((a, b) => a - b)

  if (numbers.length === 0) return null

  return (
    <sup className="ms-1 space-x-0.5 text-[10px] font-medium text-indigo-600">
      {numbers.map((n) => (
        <a
          key={n}
          href={`#${anchorPrefix}-fn-${n}`}
          className="hover:underline"
          title="Jump to source"
        >
          [{n}]
        </a>
      ))}
    </sup>
  )
}
