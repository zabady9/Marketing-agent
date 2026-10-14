import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useStudy } from '../../hooks/useStudy'
import { getStudyTitle } from '../../lib/format'
import { isRtlLanguage } from '../../lib/rtl'
import type { Block } from '../../types'
import { BlockRenderer } from '../report/blocks/BlockRenderer'
import { StepChecklist } from '../report/StepChecklist'

// Headline blocks worth showing in the chat card (the full report has the rest).
const VISUAL: Block['type'][] = ['stats', 'chart', 'board', 'matrix', 'comparison', 'table']

// One card per analysis run, keyed by study_id. It loads the run itself and
// polls while it's in progress, so it is always correct after a refresh and
// can never be attached to another run's data. `bump` changes whenever a live
// event for this run arrives, to refresh immediately instead of on the next poll.
export function AnalysisCard({ projectId, studyId, bump }: { projectId: string; studyId: string; bump: number }) {
  const { study, state, reload } = useStudy(projectId, studyId)

  useEffect(() => {
    if (bump > 0) reload()
  }, [bump, reload])

  const link = `/projects/${projectId}/studies/${studyId}`
  const shell = (children: React.ReactNode) => (
    <div className="w-full max-w-xl rounded-xl border border-indigo-200 bg-white p-4 shadow-sm">{children}</div>
  )

  if (state === 'not_found') return shell(<p className="text-xs text-gray-500">This analysis was deleted.</p>)
  if (!study) {
    return shell(
      <p className="text-xs text-gray-500">{state === 'error' ? 'Could not load this analysis.' : 'Loading analysis…'}</p>,
    )
  }

  const report = study.report ?? {}
  const steps = report.steps ?? []
  const running = study.status === 'pending' || study.status === 'running'
  const done = steps.filter((s) => s.status === 'completed' || s.status === 'failed').length
  const highlights = steps
    .flatMap((s) => s.blocks)
    .filter((b) => VISUAL.includes(b.type))
    .slice(0, 2)

  return shell(
    <div dir={isRtlLanguage(report.language) ? 'rtl' : 'ltr'}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600">Analysis</p>
          <p className="text-sm font-semibold text-gray-900">{getStudyTitle(study)}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
            running ? 'bg-amber-100 text-amber-700' : study.status === 'completed' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
          }`}
        >
          {running ? (steps.length ? `${done}/${steps.length} steps` : 'Planning…') : study.status}
        </span>
      </div>

      {running && (
        <div className="mt-3">
          {steps.length ? (
            <StepChecklist steps={steps} />
          ) : (
            <p className="text-xs text-gray-500">Researching how to do this analysis and planning the steps…</p>
          )}
        </div>
      )}

      {!running && report.answer && (
        <div className="mt-3 space-y-4">
          <BlockRenderer block={{ type: 'answer', id: 'answer', citations: [], ...report.answer }} />
          {highlights.map((b) => (
            <BlockRenderer key={b.id} block={b} compact />
          ))}
        </div>
      )}

      {study.status === 'failed' && <p className="mt-2 text-xs text-red-700">{study.error ?? 'The analysis failed.'}</p>}

      <Link to={link} className="mt-3 inline-block text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:underline">
        {running ? 'Watch progress →' : 'Open full report →'}
      </Link>
    </div>,
  )
}
