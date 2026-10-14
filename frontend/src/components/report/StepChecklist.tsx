import type { StepStatus } from '../../types'

const STEP_DOT: Record<StepStatus, string> = {
  pending: 'bg-gray-300',
  running: 'bg-amber-400 animate-pulse',
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
}

// Live progress of an analysis run — used by the report page and chat cards.
export function StepChecklist({ steps }: { steps: { id: string; title: string; status: StepStatus }[] }) {
  return (
    <ol className="space-y-1">
      {steps.map((s, i) => (
        <li key={s.id} className="flex items-center gap-2 text-xs sm:text-sm">
          <span className={`h-2 w-2 shrink-0 rounded-full ${STEP_DOT[s.status]}`} />
          <span className={s.status === 'pending' ? 'text-gray-400' : 'text-gray-700'}>
            {i + 1}. {s.title}
          </span>
        </li>
      ))}
    </ol>
  )
}
