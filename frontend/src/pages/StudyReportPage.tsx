import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useReactToPrint } from 'react-to-print'
import { getProject, getStudyById, StudyNotFoundError } from '../api'
import type { ProjectSummary, StudyResultResponse } from '../types'
import { formatDate, formatPercent } from '../lib/format'
import { isRtlLanguage } from '../lib/rtl'
import { MarketOverviewSection } from '../components/report/sections/MarketOverviewSection'
import { CompetitiveLandscapeSection } from '../components/report/sections/CompetitiveLandscapeSection'
import { FinancialFeasibilitySection } from '../components/report/sections/FinancialFeasibilitySection'
import { RiskAssessmentSection } from '../components/report/sections/RiskAssessmentSection'
import { ExecutiveSummarySection } from '../components/report/sections/ExecutiveSummarySection'
import { MethodologyAppendix } from '../components/report/sections/MethodologyAppendix'
import { GlossaryProvider } from '../components/report/GlossaryContext'

type LoadState = 'loading' | 'not_found' | 'error' | 'loaded'

const POLL_INTERVAL_MS = 5000

const VERDICT_LABELS: Record<string, string> = {
  proceed: 'Proceed',
  proceed_with_caution: 'Proceed with caution',
  do_not_proceed: 'Do not proceed',
  unavailable: 'Unavailable',
}

const VERDICT_CLASSES: Record<string, string> = {
  proceed: 'bg-emerald-100 text-emerald-700',
  proceed_with_caution: 'bg-amber-100 text-amber-700',
  do_not_proceed: 'bg-red-100 text-red-700',
  unavailable: 'bg-gray-100 text-gray-600',
}

const TOC: { id: string; label: string; has: (study: StudyResultResponse) => boolean }[] = [
  { id: 'executive-summary', label: 'Executive Summary', has: (s) => !!s.sections.executive_summary },
  { id: 'market-overview', label: 'Market Overview', has: (s) => !!s.sections.market_overview },
  {
    id: 'competitive-landscape',
    label: 'Competitive Landscape',
    has: (s) => !!s.sections.competitive_landscape,
  },
  {
    id: 'financial-feasibility',
    label: 'Financial Feasibility',
    has: (s) => !!s.sections.financial_feasibility,
  },
  { id: 'risk-assessment', label: 'Risk Assessment', has: (s) => !!s.sections.risk_assessment },
  { id: 'methodology-sources', label: 'Methodology & Sources', has: () => true },
]

export function StudyReportPage() {
  const { projectId, studyId } = useParams<{ projectId: string; studyId: string }>()
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState<string | null>(null)
  const [study, setStudy] = useState<StudyResultResponse | null>(null)
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const reportRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    if (!projectId || !studyId) return
    getProject(projectId)
      .then(setProject)
      .catch(() => {
        // Cosmetic (cover block name) only — a failure here shouldn't block the report.
      })
    return getStudyById(projectId, studyId)
      .then((data) => {
        setStudy(data)
        setState('loaded')
        setError(null)
      })
      .catch((err) => {
        if (err instanceof StudyNotFoundError) {
          setState('not_found')
          return
        }
        setError(err instanceof Error ? err.message : 'Failed to load the study report.')
        setState('error')
      })
  }, [projectId, studyId])

  useEffect(() => {
    setState('loading')
    load()
  }, [load])

  // Light polling refresh while the study is still running.
  useEffect(() => {
    if (state !== 'loaded' || study?.status !== 'running') return
    const interval = setInterval(() => {
      load()
    }, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [state, study?.status, load])

  const reactToPrintFn = useReactToPrint({
    contentRef: reportRef,
    documentTitle: `${project?.name ?? projectId ?? 'feasibility-study'} - Study Report`,
  })

  // Every MethodologyDisclosure is a click-to-reveal <details> — a reader
  // can't click anything in a PDF. Force them all open right before
  // printing (native <details> rendering already shows the content once
  // `open` is true, no CSS trick needed) and restore whatever state they
  // were actually in afterward, so the on-screen experience is unaffected
  // by having printed. (JargonTerm handles its own print visibility via
  // CSS instead — see its component — since it can't use <details> at all,
  // being embedded inline inside <p>/<span> label text.)
  useEffect(() => {
    let previouslyOpen: HTMLDetailsElement[] = []

    function openAllDetails() {
      const all = reportRef.current?.querySelectorAll('details') ?? []
      previouslyOpen = Array.from(all).filter((d) => d.open)
      all.forEach((d) => {
        d.open = true
      })
    }

    function restoreDetails() {
      const all = reportRef.current?.querySelectorAll('details') ?? []
      all.forEach((d) => {
        d.open = previouslyOpen.includes(d)
      })
    }

    window.addEventListener('beforeprint', openAllDetails)
    window.addEventListener('afterprint', restoreDetails)
    return () => {
      window.removeEventListener('beforeprint', openAllDetails)
      window.removeEventListener('afterprint', restoreDetails)
    }
  }, [])

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 px-4 py-12">
        <div className="max-w-4xl mx-auto space-y-4 animate-pulse">
          <div className="h-8 w-64 rounded bg-gray-200" />
          <div className="h-40 rounded-xl bg-gray-200" />
          <div className="h-40 rounded-xl bg-gray-200" />
          <div className="h-40 rounded-xl bg-gray-200" />
        </div>
      </div>
    )
  }

  if (state === 'not_found') {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4 px-4">
        <div className="rounded-lg border border-gray-200 bg-white px-6 py-8 text-center max-w-md">
          <p className="text-gray-700 font-medium mb-1">
            This study report couldn't be found.
          </p>
          <p className="text-sm text-gray-500">
            It may have been removed, or the link is out of date. Check the project page for its
            current reports, or ask the assistant in chat to run a new feasibility study.
          </p>
        </div>
        <Link
          to={`/projects/${projectId}`}
          className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
        >
          Go to project →
        </Link>
      </div>
    )
  }

  if (state === 'error' || !study) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4 px-4">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 max-w-md text-center">
          {error ?? 'Failed to load the study report.'}
        </div>
        <button
          onClick={load}
          className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
        >
          Retry
        </button>
        <Link to={`/projects/${projectId}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to project
        </Link>
      </div>
    )
  }

  const { sections } = study
  const language =
    sections.executive_summary?.language ??
    sections.financial_feasibility?.language ??
    sections.market_overview?.language ??
    sections.competitive_landscape?.language ??
    sections.risk_assessment?.language ??
    'en'
  const dir = isRtlLanguage(language) ? 'rtl' : 'ltr'
  const preparedDate = study.completed_at ?? study.started_at ?? study.created_at

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="print:hidden sticky top-0 z-10 border-b border-gray-200 bg-white px-4 py-3 flex items-center justify-between">
        <Link to={`/projects/${projectId}`} className="text-sm text-gray-500 hover:text-gray-700">
          ← Project
        </Link>
        <p className="text-sm font-medium text-gray-700">Study Report</p>
        <button
          onClick={() => reactToPrintFn()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
        >
          Export PDF
        </button>
      </div>

      <div ref={reportRef} dir={dir} className="px-4 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {study.status === 'running' && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
              The feasibility study is still running — this page refreshes automatically every few
              seconds.
            </div>
          )}
          {study.status === 'failed' && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              The study run failed{study.error ? `: ${study.error}` : '.'} Showing whatever sections
              completed before the failure.
            </div>
          )}
          {study.fatal_agent_failures.length > 0 && study.status !== 'failed' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              Some agents failed to complete: {study.fatal_agent_failures.join(', ')}.
            </div>
          )}

          {/* Cover block */}
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Feasibility Study Report
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-900 tracking-tight">
              {project?.name ?? 'Untitled Project'}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <span
                className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
                  VERDICT_CLASSES[study.verdict ?? 'unavailable']
                }`}
              >
                {VERDICT_LABELS[study.verdict ?? 'unavailable'] ?? study.verdict}
              </span>
              <span className="text-sm text-gray-500">
                Confidence:{' '}
                <span className="font-medium text-gray-800">
                  {study.confidence_score === null ? '—' : formatPercent(study.confidence_score * 100, 0)}
                </span>
              </span>
              <span className="text-sm text-gray-400">Prepared {formatDate(preparedDate)}</span>
            </div>
          </div>

          {/* Table of contents */}
          <nav className="rounded-xl border border-gray-200 bg-white p-4 print:hidden">
            <p className="text-xs font-semibold text-gray-500 mb-2">On this page</p>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {TOC.filter((item) => item.has(study)).map((item) => (
                <li key={item.id}>
                  <a href={`#${item.id}`} className="text-indigo-600 hover:underline">
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <GlossaryProvider terms={sections.glossary?.data.terms}>
            <div className="space-y-8">
              {sections.executive_summary && (
                <ExecutiveSummarySection data={sections.executive_summary.data} />
              )}
              {sections.market_overview && <MarketOverviewSection data={sections.market_overview.data} />}
              {sections.competitive_landscape && (
                <CompetitiveLandscapeSection data={sections.competitive_landscape.data} />
              )}
              {sections.financial_feasibility && (
                <FinancialFeasibilitySection data={sections.financial_feasibility.data} />
              )}
              {sections.risk_assessment && <RiskAssessmentSection data={sections.risk_assessment.data} />}

              <MethodologyAppendix
                market={sections.market_overview?.data}
                competitive={sections.competitive_landscape?.data}
                risk={sections.risk_assessment?.data}
                glossary={sections.glossary?.data.terms}
              />
            </div>
          </GlossaryProvider>
        </div>
      </div>
    </div>
  )
}
