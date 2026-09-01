import { useState, type ReactNode } from 'react'
import { useGlossary } from './GlossaryContext'

// Wraps a jargon acronym (TAM, ROI, Capex, ...) with a small click-to-reveal
// definition in the report's own language — the term itself stays in
// English (that's intentional, see app/tools/language.py::ENGLISH_ONLY_TERMS),
// only the explanation is localized.
//
// Deliberately NOT a <details>/<summary> (unlike MethodologyDisclosure) —
// this component gets embedded inline inside <p>/<span> label text (e.g.
// "Growth (CAGR):"), and <details> is flow content, not phrasing content,
// so nesting it inside a <p> produces invalid, browser-mangled DOM (caught
// via React's validateDOMNesting warning during testing). A plain <span>
// with a click-toggled className stays valid phrasing content everywhere.
export function JargonTerm({ term, children }: { term: string; children: ReactNode }) {
  const glossary = useGlossary()
  const definition = glossary[term]
  const [open, setOpen] = useState(false)

  if (!definition) return <>{children}</>

  return (
    <span className="jargon-term">
      {children}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`What is ${term}?`}
        aria-expanded={open}
        className="ms-1 print:hidden cursor-pointer align-middle text-[10px] leading-none text-gray-400 hover:text-indigo-600"
      >
        ⓘ
      </button>
      {/* Shown on screen only once toggled open; always shown in print —
          a reader can't click anything in a PDF. */}
      <span
        className={`mt-0.5 max-w-xs text-[11px] font-normal normal-case text-gray-500 ${
          open ? 'block' : 'hidden print:block'
        }`}
      >
        {definition}
      </span>
    </span>
  )
}
