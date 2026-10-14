import { useEffect, useId, useState } from 'react'
import type { DiagramBlock } from '../../../types'

// Mermaid is large, so it's loaded only when a report actually has a diagram.
let mermaidPromise: Promise<typeof import('mermaid').default> | null = null
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => {
      // Mermaid sizes each node by measuring its label in `fontFamily`; it
      // must be the same font the page renders (Arabic labels were clipped
      // when it measured with a different one). Extra padding absorbs the rest.
      m.default.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
        fontFamily: "'Noto Sans Arabic', 'Inter', system-ui, sans-serif",
        flowchart: { padding: 18, htmlLabels: true },
      })
      return m.default
    })
  }
  return mermaidPromise
}

// Any drawing the engine produced (flowchart, mind map, journey, timeline).
// LLM-written Mermaid can be invalid — then the plain-bullet fallback shows
// instead of an error, so the content is never lost.
export function DiagramBlockView({ block }: { block: DiagramBlock }) {
  const id = `mmd-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const [svg, setSvg] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setSvg(null)
    setFailed(false)
    loadMermaid()
      .then(async (mermaid) => {
        await mermaid.parse(block.mermaid)
        const { svg } = await mermaid.render(id, block.mermaid)
        if (!cancelled) setSvg(svg)
      })
      .catch(() => {
        // mermaid.render leaves an error element behind on failure.
        document.getElementById(`d${id}`)?.remove()
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [block.mermaid, id])

  if (failed) {
    return block.fallback ? (
      <pre className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700 font-sans">{block.fallback}</pre>
    ) : (
      <p className="text-xs text-gray-400">Diagram unavailable.</p>
    )
  }
  if (!svg) return <p className="text-xs text-gray-400">Drawing diagram…</p>
  return (
    <div
      dir="ltr"
      className="overflow-x-auto [&_svg]:mx-auto [&_svg]:max-w-full [&_svg]:h-auto"
      // Mermaid output with securityLevel 'strict' (no scripts / click handlers).
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
