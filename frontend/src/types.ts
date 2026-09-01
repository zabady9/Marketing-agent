// ── Primitives ─────────────────────────────────────────────────────────────────

export type SourceType = 'user_provided' | 'estimated' | 'calculated'
export type InputConfidence = 'high' | 'low'
export type RiskLevel = 'high' | 'medium' | 'low'
export type MarketConfidence = 'high' | 'medium' | 'low'
export type MarketPosition = 'leader' | 'challenger' | 'niche' | 'unknown'
export type QCIssue = 'citation_gap' | 'faithfulness' | 'data_gap_mismatch'
export type QCSeverity = 'warning' | 'error'
export type Verdict = 'proceed' | 'proceed_with_caution' | 'do_not_proceed'

// Per-claim sourcing classification — mirrors app/schemas/common.py::ClaimType.
export type ClaimType =
  | 'verified_fact'
  | 'assumption'
  | 'calculated_estimate'
  | 'forecast'
  | 'opinion'
  | 'unavailable'

// A section's claim_types field: field name -> its (constant) classification.
export type ClaimTypeLegend = Record<string, ClaimType>
export type AgentName =
  | 'intake'
  | 'market_sizing'
  | 'competitive'
  | 'financial'
  | 'risk'
  | 'synthesis'
  | 'citation_qc'

// ── API request ────────────────────────────────────────────────────────────────

export interface StartStudyRequest {
  business_description: string
  raw_user_input?: string
  output_language?: string
  analysis_horizon_years?: number
  problem_statement?: string
  unique_value_proposition?: string
  target_market_description?: string
  target_market_geography?: string
  target_market_type?: string
  business_model_type?: string
  pricing_unit_price?: number
  pricing_currency?: string
  pricing_model?: string
  expected_monthly_sales?: number
  capex_amount?: number
  opex_monthly_amount?: number
  funding_source?: string
  team_size?: number
  key_roles_needed?: string[]
  marketing_channels?: string[]
  competitors?: string[]
  founder_risks?: string
  study_goal?: string
}

// ── Projects ───────────────────────────────────────────────────────────────────

export interface ProjectSummary {
  id: string
  name: string
  status: string
  created_at: string
}

// ── Business profile ────────────────────────────────────────────────────────────

export interface SourcedValue<T = unknown> {
  value: T
  source: 'user_provided' | 'estimated'
  low_confidence: boolean
}

export interface CompetitorEntry {
  name: string
  source: 'user_provided' | 'estimated'
}

// ── Chat ─────────────────────────────────────────────────────────────────────────

export type ChatRole = 'user' | 'assistant' | 'tool'

export interface ChatMessageRecord {
  id: string
  role: ChatRole
  content: string
  tool_name: string | null
  study_id: string | null
  created_at: string
}

export interface ChatSessionRecord {
  id: string
  project_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface MemoryEntry {
  id: string
  content: string
  source: 'agent_extracted' | 'user_added'
  created_at: string
  updated_at: string
}

export interface ChatToolErrorPayload {
  tool_name: string
  error: string
}

export interface ChatMessageCompletedPayload {
  message_id: string | null
  role: ChatRole
  content: string
}

export interface ChatMessageDeltaPayload {
  content: string
}

export interface BusinessProfile {
  project_id: string
  raw_user_input: string
  detected_language: string
  output_language: string
  business_description: SourcedValue<string>
  problem_statement: SourcedValue<string>
  unique_value_proposition: SourcedValue<string>
  target_market_description: SourcedValue<string>
  target_market_geography: SourcedValue<string>
  target_market_type: SourcedValue<string>
  business_model_type: SourcedValue<string>
  capex: SourcedValue<number>
  capex_currency: string
  funding_source: SourcedValue<string>
  opex_monthly: SourcedValue<number>
  opex_monthly_currency: string
  pricing_unit_price: SourcedValue<number>
  pricing_currency: string
  pricing_model: SourcedValue<string>
  expected_monthly_sales: SourcedValue<number | null>
  competitors: CompetitorEntry[]
  founder_risks: SourcedValue<string>
  team_size: SourcedValue<number> | null
  key_roles_needed: SourcedValue<string[]>
  marketing_channels: SourcedValue<string[]>
  study_goal: SourcedValue<string>
  analysis_horizon_years: number
  created_at: string
  updated_at: string
}

// ── Shared schema types ────────────────────────────────────────────────────────

export interface Citation {
  url: string
  title: string
  snippet: string
}

export interface LocalizedText {
  text: string
  language: string
}

export interface CalcTrace {
  tool: 'financial_calc'
  fn: string
  inputs: Record<string, unknown>
  output: Record<string, unknown>
  input_confidence: InputConfidence
  // One-sentence plain-language explanation of the formula. Empty until the
  // backend's static CALC_METHODOLOGY lookup is wired in — see report.py.
  methodology: string
}

// Narrow shape of CalcTrace.output for the cash_flow figure specifically —
// the field is an untyped Record<string, unknown> on CashFlowFigure's own
// calculation_trace, so callers cast to this at the point of use rather than
// widening CashFlowFigure itself.
export interface CashFlowCalcOutput {
  monthly_net_cash_flow: number
  cash_position_by_month: number[]
  payback_month: number | null
  final_position: number
  horizon_months: number
}

// ── Section data shapes (matching orchestrator section_ready payloads) ─────────

export interface EstimatedMarketFigure {
  value: number | null
  currency: string
  unit: string
  source: 'estimated'
  confidence: MarketConfidence
  citations: Citation[]
  // Computed deterministically (see market_sizing.py::_classify_figure) —
  // verified_fact when a citation resolved, unavailable when value is null.
  claim_type: ClaimType
  // LLM-authored one-line derivation note. Empty until that prompt work lands.
  methodology: string
}

export interface MarketOverviewData {
  tam: EstimatedMarketFigure
  sam: EstimatedMarketFigure
  som: EstimatedMarketFigure
  growth_rate_cagr: number | null
  growth_rate_citations: Citation[]
  growth_rate_claim_type: ClaimType
  growth_rate_methodology: string
  narrative: LocalizedText
  key_insights: string[]
  citations: Citation[]
  search_queries_used: string[]
  claim_types: ClaimTypeLegend
}

export interface CompetitorProfile {
  name: string
  source: 'user_provided' | 'estimated'
  market_position: MarketPosition
  strengths: string[]
  weaknesses: string[]
  citations: Citation[]
  claim_type: ClaimType
  methodology: string
}

export interface CompetitiveLandscapeData {
  competitors: CompetitorProfile[]
  key_differentiators: string[]
  market_gaps: string[]
  narrative: LocalizedText
  citations: Citation[]
  search_queries_used: string[]
  claim_types: ClaimTypeLegend
}

export interface FinancialInputFigure {
  value: number | null
  currency: string
  source: SourceType
  claim_type: ClaimType
}

export interface CalculatedFigure {
  value: number | null
  source: 'calculated'
  input_confidence: InputConfidence
  calculation_trace?: CalcTrace
  claim_type: ClaimType
}

export interface NPVFigure extends CalculatedFigure {
  is_positive: boolean
}

// Real shape of a single scenario in sensitivity_analysis.value — see
// app/tools/financial_calc.py::run_sensitivity_analysis. Note this is
// break-even data only; the scenarios do NOT carry per-scenario NPV/ROI%
// figures (those only exist as flat, non-scenario CalculatedFigures above).
export interface SensitivityScenario {
  revenue_multiplier: number
  monthly_unit_sales: number
  break_even_units: number
  break_even_months: number
  contribution_margin_per_unit: number
  monthly_revenue_at_break_even: number
  [key: string]: unknown
}

// `value` IS the scenarios record directly — orchestrator.py's
// _financial_feasibility_data does `output.sensitivity.value["scenarios"]`,
// unwrapping the {scenarios: {...}} shape from run_sensitivity_analysis()
// before it ever reaches this payload. There is no `.scenarios` key here.
export interface SensitivityFigure {
  value: Record<'pessimistic' | 'base' | 'optimistic', SensitivityScenario>
  source: 'calculated'
  input_confidence: InputConfidence
  calculation_trace?: CalcTrace
  claim_type: ClaimType
}

export interface CashFlowFigure {
  payback_month: number | null
  final_position: number
  source: 'calculated'
  input_confidence: InputConfidence
  calculation_trace?: CalcTrace
  claim_type: ClaimType
}

// See app/tools/financial_calc.py::calculate_cost_structure.
export interface CostStructureValue {
  capex: number
  cumulative_opex: number
  total_cost: number
  horizon_months: number
}

export interface CostStructureFigure {
  value: CostStructureValue
  source: 'calculated'
  input_confidence: InputConfidence
  calculation_trace?: CalcTrace
  claim_type: ClaimType
}

// roi_year_N key is dynamic — use index signature alongside known keys
export interface FinancialFeasibilityData {
  capex: FinancialInputFigure
  opex_monthly: FinancialInputFigure
  break_even_months: CalculatedFigure
  break_even_units: CalculatedFigure
  roi_year_1: CalculatedFigure
  npv: NPVFigure
  sensitivity_analysis: SensitivityFigure
  cash_flow: CashFlowFigure
  cost_structure: CostStructureFigure
  narrative: LocalizedText
  claim_types: ClaimTypeLegend
  [key: string]: unknown
}

export interface RiskEntry {
  risk_description: string
  category: string
  probability: RiskLevel
  impact: RiskLevel
  mitigation: string
  // Previously resolved then discarded before reaching the output — now
  // threaded through so individual risks are sourceable.
  citations: Citation[]
  claim_type: ClaimType
  methodology: string
}

export interface RiskAssessmentData {
  risks: RiskEntry[]
  high_critical_count: number
  narrative: LocalizedText
  citations: Citation[]
  search_queries_used: string[]
  claim_types: ClaimTypeLegend
}

export interface ConfidenceBreakdown {
  citation_score: number
  risk_score: number
  completeness_score: number
  pipeline_score: number
  [key: string]: number
}

export interface ExecutiveSummaryData {
  verdict: Verdict
  confidence_score: number
  confidence_breakdown: ConfidenceBreakdown
  executive_summary: LocalizedText
  key_opportunities: string[]
  key_risks: string[]
  data_gaps: string[]
  contradictions: string[]
  rationale: LocalizedText
  claim_types: ClaimTypeLegend
}

// ── Parsed section (section_ready envelope + typed data) ──────────────────────

export interface ParsedSection<T> {
  section: string
  language: string
  // Only set by market_overview/financial_feasibility envelopes today — see
  // orchestrator.py::PipelineResult.to_sections_payload.
  review_recommended?: boolean
  data: T
}

// Localized jargon-term definitions (TAM, SAM, ROI, ...) — see
// app/services/glossary.py::GLOSSARY_TERMS for the canonical English term
// list; values here are localized to the section's `language`.
export interface GlossaryData {
  terms: Record<string, string>
}

export interface SectionStore {
  glossary?: ParsedSection<GlossaryData>
  market_overview?: ParsedSection<MarketOverviewData>
  competitive_landscape?: ParsedSection<CompetitiveLandscapeData>
  financial_feasibility?: ParsedSection<FinancialFeasibilityData>
  risk_assessment?: ParsedSection<RiskAssessmentData>
  executive_summary?: ParsedSection<ExecutiveSummaryData>
}

// ── SSE event payloads ─────────────────────────────────────────────────────────

export interface StudyStartedPayload {
  study_id: string
  output_language: string
  analysis_horizon_years: number
}

export interface LanguageDetectedPayload {
  study_id: string
  detected: string
  dialect?: string
  confidence: number
  method: string
  output_language: string
}

export interface IntakeWarningPayload {
  study_id: string
  field: string
  reason: string
  fallback: string
}

export interface IntakeErrorPayload {
  study_id: string
  field: string
  reason: string
}

export interface AgentStartedPayload {
  agent: AgentName
  study_id: string
}

export interface AgentCompletedPayload {
  agent: AgentName
  study_id: string
}

export interface AgentFailedPayload {
  agent: AgentName
  study_id: string
  error: string
  is_fatal: boolean
}

export interface AgentWarningPayload {
  agent: AgentName
  study_id: string
  warning: string
}

export interface SearchQuerySentPayload {
  agent: AgentName
  study_id: string
  query: string
}

export interface SearchResultsReceivedPayload {
  agent: AgentName
  study_id: string
  n_results: number
  top_urls: string[]
}

export interface CalcStartedPayload {
  fn: string
  inputs: Record<string, unknown>
}

export interface CalcCompletedPayload {
  fn: string
  output: Record<string, unknown>
  calculation_trace: CalcTrace
}

export interface CalcFailedPayload {
  study_id: string
  error: string
}

export interface SectionReadyPayload {
  section: string
  language: string
  review_recommended?: boolean
  data: unknown
}

export interface QCFlagRaisedPayload {
  study_id: string
  section: string
  issue: QCIssue
  detail: string
  section_rate?: number
}

export interface QCFlag {
  section: string
  claim: string
  issue: QCIssue
  severity: QCSeverity
  detail: string
}

export interface QCCompletedPayload {
  study_id: string
  citation_support_rate: number
  citation_threshold_passed: boolean
  faithfulness_issues: number
  executive_summary_trusted: boolean
  contradictions_in_scope: boolean
  contradictions_verified: boolean
  contradictions_faithful: boolean | null
  data_gap_mismatches: number
  total_flags: number
  flagged_sections: string[]
  coverage: Record<string, string[]>
  flags: QCFlag[]
}

export interface QCSummary {
  citation_support_rate: number
  citation_threshold_passed: boolean
  executive_summary_trusted: boolean
  total_flags: number
  contradictions_in_scope: boolean
  contradictions_verified: boolean
  contradictions_faithful: boolean | null
  flagged_sections: string[]
}

export interface StudyCompletedPayload {
  study_id: string
  verdict: Verdict
  confidence_score: number
  output_language: string
  fatal_agent_failures: string[]
  qc_summary: QCSummary | null
}

export interface StudyFailedPayload {
  study_id: string
  reason: string
}

// ── QC flag store (keyed by section name) ─────────────────────────────────────

export type QCFlagStore = Record<string, QCFlagRaisedPayload[]>

// ── Top-level study state (owned by useStudy reducer) ─────────────────────────

export type StudyStatus = 'idle' | 'running' | 'partial_failure' | 'failed' | 'completed'

export type AgentStatus = 'running' | 'completed' | 'failed'

export interface StudyState {
  status: StudyStatus
  studyId: string | null
  outputLanguage: string | null
  analysisHorizonYears: number
  languageDetected: LanguageDetectedPayload | null
  intakeWarnings: IntakeWarningPayload[]
  // agent name → current status (only agents that have started appear here)
  agents: Record<string, AgentStatus>
  // search/calc activity per agent — for progress sub-rows
  searchActivity: Record<string, SearchQuerySentPayload[]>
  // sections: de-duped by section name; second section_ready for same key is ignored
  sections: SectionStore
  // QC flags per section
  qcFlags: QCFlagStore
  qcCompleted: QCCompletedPayload | null
  studyCompleted: StudyCompletedPayload | null
  // true unless qc_completed sets executive_summary_trusted=false
  executiveSummaryTrusted: boolean
  failureReason: string | null
  // set on intake_error — drives distinct UI vs other failures
  failureField: string | null
}

// ── GET /api/projects/{id}/study response (app/schemas/study.py) ──────────────

export type StudyRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface StudyResultResponse {
  id: string
  project_id: string
  status: StudyRunStatus
  // Same envelope shape as SectionStore — only sections that completed are
  // present, whether the run finished cleanly or hit a fatal failure partway.
  sections: SectionStore
  verdict: Verdict | 'unavailable' | null
  confidence_score: number | null
  qc_summary: QCSummary | null
  fatal_agent_failures: string[]
  error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}
