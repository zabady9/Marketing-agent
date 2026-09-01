import { createContext, useContext, type ReactNode } from 'react'

// Localized jargon-term definitions (TAM, SAM, ROI, ...), keyed by term.
// Populated once from the `glossary` pseudo-section (see types.ts::GlossaryData)
// and shared via context so JargonTerm doesn't need prop-drilling through
// every section/component that happens to display one of these terms.
const GlossaryContext = createContext<Record<string, string>>({})

export function GlossaryProvider({
  terms,
  children,
}: {
  terms: Record<string, string> | undefined
  children: ReactNode
}) {
  return <GlossaryContext.Provider value={terms ?? {}}>{children}</GlossaryContext.Provider>
}

export function useGlossary(): Record<string, string> {
  return useContext(GlossaryContext)
}
