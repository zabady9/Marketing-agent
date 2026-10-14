import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useReactToPrint } from 'react-to-print'
import { exportStudyMarkdown, getProject } from '../api'
import type { AnalysisStep, ProjectSummary } from '../types'
import { formatDate, getStudyTitle } from '../lib/format'
import { isRtlLanguage } from '../lib/rtl'
import { useStudy } from '../hooks/useStudy'
import { buildCitationRegistry, type CitationRegistry } from '../components/report/citations'
import { CitationFootnotes } from '../components/report/CitationFootnotes'
import { BlockRenderer } from '../components/report/blocks/BlockRenderer'
import { Markdown } from '../components/report/blocks/Markdown'
import { StepChecklist } from '../components/report/StepChecklist'

const ANCHOR = 'src'

function StepSection({ step, index, registry }: { step: AnalysisStep; index: number; registry: CitationRegistry }) {
  return (
    <section id={`step-${step.id}`} className="scroll-mt-20 rounded-xl border border-gray-200 bg-white p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-semibold text-white">
          {index + 1}
        </span>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900">{step.title}</h2>
          {step.objective && <p className="text-sm text-gray-500">{step.objective}</p>}
        </div>
      </div>

      {step.status === 'pending' || step.status === 'running' ? (
        <p className="mt-4 text-sm text-gray-400">{step.status === 'running' ? 'Working on this step…' : 'Waiting…'}</p>
      ) : step.status === 'failed' && step.blocks.length === 0 ? (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          This step couldn't be completed{step.error ? `: ${step.error}` : '.'}
        </p>
      ) : (
        <div className="mt-4 space-y-6">
          {step.summary && <Markdown text={step.summary} className="text-sm font-medium text-gray-800" />}
          {step.blocks.map((block) => (
            <BlockRenderer key={block.id} block={block} registry={registry} anchorPrefix={ANCHOR} />
          ))}
        </div>
      )}
    </section>
  )
}

export function StudyReportPage() {
  const { projectId, studyId } = useParams<{ projectId: string; studyId: string }>()
  const { study, state, error, reload } = useStudy(projectId, studyId)
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const reportRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!projectId) return
    getProject(projectId).then(setProject).catch(() => {})
  }, [projectId])

  const report = useMemo(() => study?.report ?? {}, [study])
  const steps = useMemo(() => report.steps ?? [], [report])
  const registry = useMemo(
    () => buildCitationRegistry([report.sources, ...steps.flatMap((s) => s.blocks.map((b) => b.citations))]),
    [report.sources, steps],
  )
  const methodRegistry = useMemo(() => buildCitationRegistry([report.method_sources]), [report.method_sources])

  const print = useReactToPrint({
    contentRef: reportRef,
    documentTitle: study ? getStudyTitle(study) : 'analysis',
  })

  const handleExportMarkdown = () => {
    if (!projectId || !studyId || exporting) return
    setExporting(true)
    setExportError(null)
    exportStudyMarkdown(projectId, studyId)
      .then((markdown) => {
        const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }))
        const a = document.createElement('a')
        a.href = url
        a.download = `${study ? getStudyTitle(study) : 'analysis'}.md`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => setExportError(err instanceof Error ? err.message : 'Export failed.'))
      .finally(() => setExporting(false))
  }

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 px-4 py-12">
        <div className="max-w-4xl mx-auto space-y-4 animate-pulse">
          <div className="h-8 w-64 rounded bg-gray-200" />
          <div className="h-40 rounded-xl bg-gray-200" />
          <div className="h-40 rounded-xl bg-gray-200" />
        </div>
      </div>
    )
  }

  if (!study) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4 px-4">
        <div className="max-w-md rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-center text-sm text-red-700">
          {state === 'not_found' ? 'This analysis does not exist or was deleted.' : (error ?? 'Failed to load the analysis.')}
        </div>
        {state === 'error' && (
          <button onClick={reload} className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">
            Retry
          </button>
        )}
        <Link to={`/projects/${projectId}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to project
        </Link>
      </div>
    )
  }

  const running = study.status === 'pending' || study.status === 'running'
  const dir = isRtlLanguage(report.language) ? 'rtl' : 'ltr'
  const doneSteps = steps.filter((s) => s.status === 'completed' || s.status === 'failed').length

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="print:hidden sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3">
        <Link to={`/projects/${projectId}/chat`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Chat
        </Link>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExportMarkdown}
            disabled={exporting || running}
            className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Export Markdown'}
          </button>
          <button
            onClick={() => print()}
            disabled={running}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Export PDF
          </button>
        </div>
      </div>

      <div ref={reportRef} dir={dir} className="px-4 py-8">
        <div className="mx-auto max-w-4xl space-y-6">
          {exportError && (
            <div className="print:hidden rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{exportError}</div>
          )}

          <div className="rounded-xl border border-gray-200 bg-white p-6">
            {project?.name && <p className="text-xs font-medium uppercase tracking-wide text-gray-400">{project.name}</p>}
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-gray-900">{getStudyTitle(study)}</h1>
            <p className="mt-1 text-xs text-gray-400">{formatDate(study.completed_at ?? study.started_at ?? study.created_at)}</p>
            {study.goal && (
              <div className="mt-4">
                <p className="text-xs font-medium text-gray-500">Your question</p>
                <p className="text-sm text-gray-900">{study.goal}</p>
              </div>
            )}
            {report.rationale && (
              <div className="mt-3">
                <p className="text-xs font-medium text-gray-500">Why this analysis</p>
                <p className="text-sm text-gray-700">{report.rationale}</p>
                {!!report.frameworks?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {report.frameworks.map((f) => (
                      <span key={f} className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">{f}</span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {running && (
            <div className="print:hidden rounded-xl border border-indigo-200 bg-indigo-50 p-5">
              <p className="text-sm font-medium text-indigo-800">
                {steps.length
                  ? `Working… ${doneSteps}/${steps.length} steps done`
                  : 'Researching how to do this analysis and planning the steps…'}
              </p>
              {steps.length > 0 && (
                <div className="mt-3">
                  <StepChecklist steps={steps} />
                </div>
              )}
              <p className="mt-2 text-xs text-indigo-600">This page updates by itself.</p>
            </div>
          )}
          {study.status === 'failed' && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              The analysis failed{study.error ? `: ${study.error}` : '.'}
              {steps.some((s) => s.blocks.length) ? ' Showing the steps that completed.' : ''}
            </div>
          )}

          {report.answer && (
            <section className="rounded-xl border border-indigo-200 bg-white p-6">
              <BlockRenderer block={{ type: 'answer', id: 'answer', citations: [], ...report.answer }} />
              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                {!!report.findings?.length && (
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Key findings</p>
                    <ul className="list-disc space-y-1 ps-5 text-sm text-gray-700">
                      {report.findings.map((f, i) => (
                        <li key={i}>{f}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {!!report.recommendations?.length && (
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Recommendations</p>
                    <ol className="list-decimal space-y-1 ps-5 text-sm text-gray-700">
                      {report.recommendations.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            </section>
          )}

          {steps.length > 0 && !running && (
            <nav className="print:hidden rounded-xl border border-gray-200 bg-white p-4">
              <p className="mb-2 text-xs font-semibold text-gray-500">Steps</p>
              <ol className="grid gap-1 text-sm sm:grid-cols-2">
                {steps.map((s, i) => (
                  <li key={s.id}>
                    <a href={`#step-${s.id}`} className="text-indigo-600 hover:underline">
                      {i + 1}. {s.title}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          )}

          {steps.map((step, i) => (
            <StepSection key={step.id} step={step} index={i} registry={registry} />
          ))}

          {(registry.citations.length > 0 || methodRegistry.citations.length > 0) && (
            <section className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold text-gray-900">Sources</h2>
              <CitationFootnotes registry={registry} anchorPrefix={ANCHOR} />
              {methodRegistry.citations.length > 0 && (
                <div className="mt-5">
                  <p className="text-xs font-semibold text-gray-500">How this analysis was built</p>
                  <p className="mt-1 text-xs text-gray-500">
                    The method was researched from these sources, then planned as {steps.length} steps.
                  </p>
                  <CitationFootnotes registry={methodRegistry} anchorPrefix="method" />
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
