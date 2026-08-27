import type { StartStudyRequest } from '../../types'

export interface WizardFieldError {
  field: string
  reason: string
}

export interface WizardState {
  business_description: string
  problem_statement: string
  unique_value_proposition: string

  target_market_description: string
  target_market_geography: string
  target_market_type: '' | 'B2C' | 'B2B'

  business_model_type: string
  pricing_unit_price: string
  pricing_currency: string
  pricing_model: string
  expected_monthly_sales: string

  capex_amount: string
  opex_monthly_amount: string
  funding_source: '' | 'self-funded' | 'loan' | 'investors' | 'other'

  team_size: string
  key_roles_needed: string[]
  marketing_channels: string[]

  competitors: string[]
  founder_risks: string

  analysis_horizon_years: string
  output_language: string
  study_goal: '' | 'validate idea' | 'secure funding' | 'internal planning' | 'other'

  // One free-text "anything else?" box per step, indexed by step number.
  notes: string[]
}

export const STEP_TITLES = [
  'Business Concept',
  'Target Market',
  'Business Model & Pricing',
  'Costs & Investment',
  'Team & Operations',
  'Competition & Risks',
  'Goals & Horizon',
]

export const STEP_COUNT = STEP_TITLES.length

// The only step with a client-side required field — the wizard's replacement
// for the old server-side "missing price" 422 gate.
export const PRICING_STEP = 2

export function createInitialWizardState(): WizardState {
  return {
    business_description: '',
    problem_statement: '',
    unique_value_proposition: '',
    target_market_description: '',
    target_market_geography: '',
    target_market_type: '',
    business_model_type: '',
    pricing_unit_price: '',
    pricing_currency: 'USD',
    pricing_model: '',
    expected_monthly_sales: '',
    capex_amount: '',
    opex_monthly_amount: '',
    funding_source: '',
    team_size: '',
    key_roles_needed: [],
    marketing_channels: [],
    competitors: [],
    founder_risks: '',
    analysis_horizon_years: '3',
    output_language: '',
    study_goal: '',
    notes: Array.from({ length: STEP_COUNT }, () => ''),
  }
}

export function validateStep(step: number, state: WizardState): string | null {
  if (step === 0 && state.business_description.trim().length < 20) {
    return 'Please describe your business idea in at least 20 characters.'
  }
  if (step === PRICING_STEP) {
    const price = parseFloat(state.pricing_unit_price)
    if (!state.pricing_unit_price.trim() || Number.isNaN(price) || price <= 0) {
      return "Please enter a unit price greater than 0 — the study can't build a financial model without one."
    }
  }
  return null
}

function numOrUndefined(raw: string): number | undefined {
  if (!raw.trim()) return undefined
  const n = parseFloat(raw)
  return Number.isNaN(n) ? undefined : n
}

function intOrUndefined(raw: string): number | undefined {
  if (!raw.trim()) return undefined
  const n = parseInt(raw, 10)
  return Number.isNaN(n) ? undefined : n
}

function strOrUndefined(raw: string): string | undefined {
  const trimmed = raw.trim()
  return trimmed ? trimmed : undefined
}

function listOrUndefined(list: string[]): string[] | undefined {
  return list.length > 0 ? list : undefined
}

// raw_user_input is optional on the request (the server can synthesize its own
// fallback from structured fields alone), but that fallback has no way to see
// the per-step "anything else?" notes — those only exist client-side. Building
// raw_user_input here, from the description/problem/UVP plus every non-empty
// note, is what actually gets that free text into the LLM extraction pass.
export function buildSubmitPayload(state: WizardState): StartStudyRequest {
  const parts: string[] = [`Business: ${state.business_description.trim()}`]
  if (state.problem_statement.trim()) {
    parts.push(`Problem: ${state.problem_statement.trim()}`)
  }
  if (state.unique_value_proposition.trim()) {
    parts.push(`Unique value proposition: ${state.unique_value_proposition.trim()}`)
  }
  state.notes.forEach((note, i) => {
    if (note.trim()) {
      parts.push(`Additional notes (${STEP_TITLES[i]}): ${note.trim()}`)
    }
  })

  return {
    business_description: state.business_description.trim(),
    raw_user_input: parts.join('\n'),
    problem_statement: strOrUndefined(state.problem_statement),
    unique_value_proposition: strOrUndefined(state.unique_value_proposition),
    target_market_description: strOrUndefined(state.target_market_description),
    target_market_geography: strOrUndefined(state.target_market_geography),
    target_market_type: state.target_market_type || undefined,
    business_model_type: strOrUndefined(state.business_model_type),
    pricing_unit_price: numOrUndefined(state.pricing_unit_price),
    pricing_currency: state.pricing_currency.trim() || 'USD',
    pricing_model: strOrUndefined(state.pricing_model),
    expected_monthly_sales: numOrUndefined(state.expected_monthly_sales),
    capex_amount: numOrUndefined(state.capex_amount),
    opex_monthly_amount: numOrUndefined(state.opex_monthly_amount),
    funding_source: state.funding_source || undefined,
    team_size: intOrUndefined(state.team_size),
    key_roles_needed: listOrUndefined(state.key_roles_needed),
    marketing_channels: listOrUndefined(state.marketing_channels),
    competitors: listOrUndefined(state.competitors),
    founder_risks: strOrUndefined(state.founder_risks),
    study_goal: state.study_goal || undefined,
    analysis_horizon_years: intOrUndefined(state.analysis_horizon_years) || 3,
    output_language: strOrUndefined(state.output_language),
  }
}
