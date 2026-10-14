import type { ReactNode } from 'react'

// Shared card shell for in-chat cards (charts, artifacts, analysis cards).

export function SectionCardShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 px-4 py-3 max-w-md">
      <p className="text-xs font-semibold text-indigo-700 mb-2">{title}</p>
      {children}
    </div>
  )
}
