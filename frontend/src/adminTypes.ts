// Types for the /admin data-management panel — mirrors the admin-only
// backend schemas under app/schemas/admin (locked contract, backend landing
// in parallel). These are separate from types.ts's public-facing types
// because every admin response additionally carries `deleted_at`.

import type { QCSummary, SectionStore, StudyRunStatus, Verdict } from './types'

// ── Pagination envelope ─────────────────────────────────────────────────────

export interface PagedResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface AdminListParams {
  limit?: number
  offset?: number
  include_deleted?: boolean
  [key: string]: string | number | boolean | undefined
}

// ── Project ──────────────────────────────────────────────────────────────────

export interface ProjectAdminResponse {
  id: string
  name: string
  status: string
  deleted_at: string | null
  created_at: string
  updated_at: string
  active_study_count: number
  active_chat_session_count: number
}

export interface ProjectAdminUpdate {
  name?: string
  status?: string
}

// ── BusinessProfile (nested under Project — read-only in admin, reuses the
// public shapes from types.ts/api.ts) ───────────────────────────────────────

export interface BusinessProfileUpdate {
  business_description?: string
  problem_statement?: string
  unique_value_proposition?: string
  target_market_description?: string
  target_market_geography?: string
  target_market_type?: string
  business_model_type?: string
  capex_amount?: number
  capex_currency?: string
  funding_source?: string
  opex_monthly_amount?: number
  opex_monthly_currency?: string
  pricing_unit_price?: number
  pricing_currency?: string
  pricing_model?: string
  expected_monthly_sales?: number
  competitors?: string[]
  founder_risks?: string
  team_size?: number
  key_roles_needed?: string[]
  marketing_channels?: string[]
  study_goal?: string
  analysis_horizon_years?: number
}

// ── StudyResult ──────────────────────────────────────────────────────────────

export interface StudyResultAdminResponse {
  id: string
  project_id: string
  status: StudyRunStatus
  sections: SectionStore | Record<string, unknown>
  verdict: Verdict | 'unavailable' | null
  confidence_score: number | null
  qc_summary: QCSummary | null
  fatal_agent_failures: string[]
  error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface StudyResultAdminCreate {
  project_id: string
  status?: string
  sections?: Record<string, unknown>
  verdict?: string | null
  confidence_score?: number | null
  qc_summary?: Record<string, unknown> | null
  fatal_agent_failures?: string[]
  error?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export type StudyResultAdminUpdate = Partial<StudyResultAdminCreate>

// ── ChatSession ──────────────────────────────────────────────────────────────

export interface ChatSessionAdminResponse {
  id: string
  project_id: string
  title: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface ChatSessionAdminUpdate {
  title?: string | null
}

// ── ChatMessage ──────────────────────────────────────────────────────────────

export interface ChatMessageAdminResponse {
  id: string
  role: string
  content: string
  tool_name: string | null
  study_id: string | null
  created_at: string
  deleted_at: string | null
}

export interface ChatMessageAdminUpdate {
  content?: string
  role?: string
  tool_name?: string | null
  study_id?: string | null
}

// ── MemoryEntry ──────────────────────────────────────────────────────────────

export interface MemoryEntryAdminResponse {
  id: string
  content: string
  source: string
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface MemoryEntryAdminUpdate {
  content?: string
  source?: string
}

// ── GlossaryCache (primary key is `language`, not `id`) ─────────────────────

export interface GlossaryCacheAdminResponse {
  language: string
  terms: Record<string, string>
  created_at: string
  deleted_at: string | null
}

export interface GlossaryCacheAdminUpdate {
  terms: Record<string, string>
}

// Fixed set of known glossary keys — see app/services/glossary.py::GLOSSARY_TERMS.
export const GLOSSARY_TERM_KEYS = [
  'TAM',
  'SAM',
  'SOM',
  'ROI',
  'NPV',
  'IRR',
  'CAGR',
  'EBITDA',
  'Capex',
  'Opex',
  'Break-even',
  'KPI',
  'MVP',
  'SaaS',
  'B2B',
  'B2C',
  'D2C',
] as const
