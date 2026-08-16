export interface Workspace {
  id: string
  name: string
  autonomy_level: string
  created_at: string
}

// ── Analysis Subject (replaces BrandProfile) ──────────────────────────────────

export interface BusinessLine {
  name: string
  description: string
  notes?: string | null
}

export interface TrackedCompetitor {
  name: string
  description?: string | null
  notes?: string | null
}

export interface AnalysisSubject {
  id: string
  workspace_id: string
  subject_name: string | null
  legal_name: string | null
  subject_type: string | null
  industry: string | null
  subject_description: string | null
  business_lines: BusinessLine[]
  tracked_competitors: TrackedCompetitor[]
  areas_of_interest: string[]
  setup_status: string
  extra: Record<string, unknown>
  created_at: string
  updated_at: string
}

// ── Knowledge ─────────────────────────────────────────────────────────────────

export interface KnowledgeDocument {
  id: string
  workspace_id: string
  filename: string
  doc_type: string
  storage_path: string
  status: 'processing' | 'indexed' | 'failed'
  uploaded_at: string
}

export interface KnowledgeChunk {
  id: string
  document_id: string
  workspace_id: string
  content: string
  chunk_metadata: Record<string, unknown>
  created_at: string
}

// ── Reports (consulting_analyses) ─────────────────────────────────────────────

export type ReportStatus = 'generating' | 'ready' | 'failed'

export interface Report {
  id: string
  workspace_id: string
  analysis_type: string
  status: ReportStatus
  results: Record<string, unknown> | null
  error: string | null
  created_at: string
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  metadata_: Record<string, unknown>
  agent_id?: string | null
  meeting_id?: string | null
  turn_index?: number | null
  created_at: string
}

export interface ChatSession {
  id: string
  workspace_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[]
}

// ── Visual blocks (emitted via SSE after `done`) ──────────────────────────────

export type VisualType =
  | 'bar_chart'
  | 'line_chart'
  | 'area_chart'
  | 'table'
  | 'metric_card'
  | 'radar_chart'
  | 'pie_chart'
  | 'donut_chart'
  | 'stacked_bar_chart'
  | 'gauge'
  | 'comparison_grid'
  | 'timeline'
  | 'word_cloud'
  | 'progress_list'

export interface VisualBlock {
  type: VisualType
  title: string
  data: Record<string, unknown>
}

export interface SourceRef {
  title: string
  url: string
  fetched_at: string
}

export interface ConsultVisuals {
  visuals: VisualBlock[]
  sources: SourceRef[]
}
