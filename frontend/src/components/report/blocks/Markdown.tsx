import type { ReactNode } from 'react'

// Minimal, safe Markdown for model-written text blocks: headings, bullet and
// numbered lists, paragraphs, **bold** and *italic*. No HTML is ever injected.
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let key = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    out.push(
      tok.startsWith('**') ? (
        <strong key={key++} className="font-semibold text-gray-900">{tok.slice(2, -2)}</strong>
      ) : (
        <em key={key++}>{tok.slice(1, -1)}</em>
      ),
    )
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  const lines = (text || '').split('\n')
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let para: string[] = []

  const flushPara = () => {
    if (para.length) blocks.push(<p key={blocks.length}>{inline(para.join(' '))}</p>)
    para = []
  }
  const flushList = () => {
    if (!list) return
    const items = list.items.map((it, i) => <li key={i}>{inline(it)}</li>)
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length} className="list-decimal ps-5 space-y-1">{items}</ol>
      ) : (
        <ul key={blocks.length} className="list-disc ps-5 space-y-1">{items}</ul>
      ),
    )
    list = null
  }

  for (const raw of lines) {
    const line = raw.trim()
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line)
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    if (!line) {
      flushPara()
      flushList()
    } else if (heading) {
      flushPara()
      flushList()
      blocks.push(<p key={blocks.length} className="font-semibold text-gray-900">{inline(heading[1])}</p>)
    } else if (bullet || numbered) {
      flushPara()
      const ordered = !!numbered
      if (list && list.ordered !== ordered) flushList()
      if (!list) list = { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
    } else {
      flushList()
      para.push(line)
    }
  }
  flushPara()
  flushList()
  return <div className={`space-y-2 ${className}`}>{blocks}</div>
}
