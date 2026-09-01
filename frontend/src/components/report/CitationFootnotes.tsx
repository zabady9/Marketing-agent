import type { CitationRegistry } from './citations'

// Numbered footnote list at the bottom of a section, numbered 1..N to match
// that section's SourceBadge links (see citations.ts::buildCitationRegistry).
export function CitationFootnotes({
  registry,
  anchorPrefix,
}: {
  registry: CitationRegistry
  anchorPrefix: string
}) {
  if (registry.citations.length === 0) return null

  return (
    <div className="mt-4 border-t border-gray-100 pt-3">
      <p className="text-xs font-semibold text-gray-500 mb-1.5">Sources</p>
      <ol className="space-y-1 text-xs text-gray-600">
        {registry.citations.map((citation, i) => (
          <li key={citation.url} id={`${anchorPrefix}-fn-${i + 1}`} className="flex gap-1.5">
            <span className="shrink-0 text-gray-400">[{i + 1}]</span>
            <span>
              <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-600 hover:underline break-all"
              >
                {citation.title || citation.url}
              </a>
              {citation.snippet && (
                <span className="block text-gray-400 italic">{citation.snippet}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
