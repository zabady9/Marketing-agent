// Shared per-section anchor prefixes — used both for SourceBadge links inside
// a section and for the matching CitationFootnotes list rendered in the
// Methodology & Sources appendix, so the two always agree.
export const ANCHOR_PREFIX = {
  market: 'market_overview',
  competitive: 'competitive_landscape',
  financial: 'financial_feasibility',
  risk: 'risk_assessment',
  executive: 'executive_summary',
} as const
