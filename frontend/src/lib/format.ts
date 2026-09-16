// Shared number/currency formatting for the study report and chat cards.
import type { SectionStore, StudyPhase, StudyType, Verdict } from '../types'

export function formatNumber(n: number | null | undefined, maximumFractionDigits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString(undefined, { maximumFractionDigits })
}

export function formatCurrency(
  n: number | null | undefined,
  currency = 'USD',
  maximumFractionDigits = 0,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  try {
    return n.toLocaleString(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits,
    })
  } catch {
    // Unknown/invalid currency code — fall back to a plain number + code.
    return `${formatNumber(n, maximumFractionDigits)} ${currency}`
  }
}

export function formatPercent(n: number | null | undefined, maximumFractionDigits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${formatNumber(n, maximumFractionDigits)}%`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

const PHASE_TITLES: Record<StudyPhase, string> = {
  market_sizing: 'Market Sizing Report',
  competitive: 'Competitive Analysis Report',
  financial: 'Financial Analysis Report',
  risk: 'Risk Analysis Report',
  synthesis: 'Executive Summary Report',
}

const VERDICT_TITLE_LABELS: Record<Verdict, string> = {
  proceed: 'Proceed',
  proceed_with_caution: 'Proceed with caution',
  do_not_proceed: 'Do not proceed',
}

// A short, content-derived detail unique to THIS run's actual result — not
// just its type — so two Competitive Analysis reports for the same project
// don't share one identical title. Pulled straight from the one figure a
// reader would look for first in that phase's own section; returns null
// (title falls back to the plain phase label) whenever that run's data
// isn't there yet (still running, failed before producing it, or nulled out
// by the citation guard).
function getStudyDetail(study: {
  study_type: StudyType
  requested_phase: StudyPhase | null
  sections: SectionStore
}): string | null {
  const phase = study.study_type === 'single_phase' ? study.requested_phase : null

  if (phase === 'market_sizing') {
    const tam = study.sections.market_overview?.data.tam
    return tam && tam.value != null ? `${formatCurrency(tam.value, tam.currency, 0)} TAM` : null
  }
  if (phase === 'competitive') {
    const n = study.sections.competitive_landscape?.data.competitors.length
    return n ? `${n} competitor${n === 1 ? '' : 's'} analyzed` : null
  }
  if (phase === 'financial') {
    const months = study.sections.financial_feasibility?.data.break_even_months.value
    return months != null ? `Break-even in ${formatNumber(months, 0)} mo` : null
  }
  if (phase === 'risk') {
    const n = study.sections.risk_assessment?.data.risks.length
    return n ? `${n} risk${n === 1 ? '' : 's'} identified` : null
  }
  // Synthesis (single-phase) and a full study both end in an
  // executive_summary — its verdict is the headline result either way.
  const verdict = study.sections.executive_summary?.data.verdict
  return verdict ? VERDICT_TITLE_LABELS[verdict] : null
}

// Prefers the LLM-generated title (app.services.study_title —
// content-specific, e.g. "Competitive Landscape: 5 Direct Rivals in the US
// Meal-Kit Market") so each report reads as its own result rather than a
// repeated category label. Falls back to a deterministic label (+ a
// content-derived detail, + a time-of-day suffix that guarantees no two
// reports ever collide) only when generation failed/timed out or the row
// predates this feature — never leaves a report title-less.
export function getStudyTitle(study: {
  study_type: StudyType
  requested_phase: StudyPhase | null
  title: string | null
  sections: SectionStore
  created_at: string
  started_at: string | null
  completed_at: string | null
}): string {
  if (study.title) return study.title

  const phase = study.study_type === 'single_phase' ? study.requested_phase : null
  const base = (phase && PHASE_TITLES[phase]) || 'Feasibility Study Report'
  const detail = getStudyDetail(study)
  const time = formatTime(study.completed_at ?? study.started_at ?? study.created_at)
  return `${detail ? `${base} — ${detail}` : base} (${time})`
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}
