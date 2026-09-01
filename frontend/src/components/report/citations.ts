import type { Citation } from '../../types'

export interface CitationRegistry {
  // De-duped citations in first-seen order — index i corresponds to
  // footnote number i+1.
  citations: Citation[]
  // url -> 1-based footnote number
  indexOf: (url: string) => number | undefined
}

// Builds a per-section, de-duped-by-URL citation registry so every claim's
// SourceBadge can point at a stable footnote number, numbered 1..N *within
// that section* (not globally) — a partial/failed study then never has gaps
// in another section's numbering.
//
// Pass every citations array that appears anywhere in the section (the
// section-level aggregate first, then any per-claim arrays) — arrays are
// scanned in order and first-seen URL wins the earlier number.
export function buildCitationRegistry(citationArrays: (Citation[] | undefined)[]): CitationRegistry {
  const citations: Citation[] = []
  const indexByUrl = new Map<string, number>()

  for (const arr of citationArrays) {
    if (!arr) continue
    for (const citation of arr) {
      if (!citation?.url || indexByUrl.has(citation.url)) continue
      citations.push(citation)
      indexByUrl.set(citation.url, citations.length)
    }
  }

  return {
    citations,
    indexOf: (url: string) => indexByUrl.get(url),
  }
}
