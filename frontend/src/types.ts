// Types shared across the app. Analysis reports are generic: a report is a
// list of steps, each holding typed blocks — mirrors app/schemas/blocks.py
// and app/analysis/engine.py. Nothing here is specific to one analysis.

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

// "pending"/"streaming" only ever appear on an assistant row for a
// generation still in flight on the backend — see
// app.services.chat_agent.run_chat_turn. user/tool rows are always
// "complete".
export type ChatMessageStatus = 'pending' | 'streaming' | 'complete' | 'error'

// Matches app/schemas/chart.py::ChartSeries — one data series for a
// generate_chart_tool result. `data` has exactly one entry per `categories`
// entry, in the same order (enforced backend-side).
export interface ChartSeries {
  name: string
  data: (number | null)[]
}

// Matches app/schemas/chart.py::ChartSpec (model_dump(), plain snake_case
// JSON). A pie chart always has exactly one series; series always has at
// least one entry; categories always has at least one entry.
export interface ChartSpec {
  chart_type: 'bar' | 'line' | 'pie'
  title: string
  categories: string[]
  series: ChartSeries[]
  x_label: string | null
  y_label: string | null
}

// Matches app/schemas/artifact.py::ArtifactSummary — metadata for a
// generated DOCX/PPTX/PDF file, never the raw bytes (fetched separately via
// downloadChatArtifact).
export interface ArtifactSummary {
  id: string
  format: 'docx' | 'pptx' | 'pdf'
  title: string
  filename: string
  size_bytes: number
}

// A row of the project's generated-files list (GET .../chat/artifacts).
export interface ArtifactListItem extends ArtifactSummary {
  created_at: string
}

// Matches app/schemas/attachment.py::AttachmentSummary — a user-uploaded
// chat file. `kind` says how the agent sees it: as the file itself
// (gemini_file), as extracted text, or by name/type only (metadata_only).
export type AttachmentStatus = 'pending_upload' | 'processing' | 'ready' | 'failed'

export interface AttachmentSummary {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  status: AttachmentStatus
  kind: 'gemini_file' | 'text' | 'metadata_only' | null
  error: string | null
  created_at: string
}

// Where the browser PUTs an attachment's bytes — a GCS signed URL in
// production, the backend's own .../content route locally.
export interface UploadTarget {
  url: string
  method: string
  headers: Record<string, string>
}

export interface ChatMessageRecord {
  id: string
  role: ChatRole
  content: string
  tool_name: string | null
  study_id: string | null
  status: ChatMessageStatus
  created_at: string
  // Set only on a persisted tool-role row for a successful
  // generate_chart_tool call — see app/models/chat.py::ChatMessage.chart_data.
  chart_data: ChartSpec | null
  // Set only on a persisted tool-role row for a successful
  // generate_presentation_tool/generate_word_document_tool/
  // generate_pdf_report_tool/revise_artifact_tool call — see
  // app/models/chat.py::ChatMessage.artifact_id.
  artifact_data: ArtifactSummary | null
  // Files the user sent with this message (user rows only).
  attachments: AttachmentSummary[]
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

// Payload for the chat_chart_ready SSE event (app/sse.py::SSEEvent.CHAT_CHART_READY)
// — pushed live the moment a generate_chart_tool call succeeds.
export interface ChatChartReadyPayload {
  message_id: string
  tool_name: string
  chart: ChartSpec
}

// Payload for the chat_artifact_ready SSE event
// (app/sse.py::SSEEvent.CHAT_ARTIFACT_READY) — pushed live the moment a
// generate_presentation_tool/generate_word_document_tool/
// generate_pdf_report_tool/revise_artifact_tool call succeeds, mirroring
// ChatChartReadyPayload.
export interface ChatArtifactReadyPayload {
  message_id: string
  tool_name: string
  artifact: ArtifactSummary
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
  additional_context: string | null
  created_at: string
  updated_at: string
}

// ── Analysis reports ────────────────────────────────────────────────────────────

export interface Citation {
  url: string
  title: string
  snippet: string
}

export type Basis = 'sourced' | 'calculated' | 'estimate'
export type Level = 'high' | 'medium' | 'low'

interface BlockBase {
  id: string
  title?: string | null
  citations: Citation[]
}

export interface AnswerBlock extends BlockBase {
  type: 'answer'
  headline: string
  body: string
  confidence: Level
}

export interface TextBlock extends BlockBase {
  type: 'text'
  kind: 'reasoning' | 'explanation' | 'narrative' | 'assumption' | 'note'
  markdown: string
}

export interface StatItem {
  label: string
  value: string
  unit: string
  note: string
  basis: Basis
}

export interface StatsBlock extends BlockBase {
  type: 'stats'
  items: StatItem[]
}

export type BlockChartType =
  | 'bar'
  | 'line'
  | 'area'
  | 'pie'
  | 'stacked_bar'
  | 'scatter'
  | 'radar'
  | 'funnel'

export interface ChartBlock extends BlockBase {
  type: 'chart'
  chart_type: BlockChartType
  categories: string[]
  series: { name: string; data: (number | null)[] }[]
  x_label: string | null
  y_label: string | null
  unit: string
  basis: Basis
}

export interface TableBlock extends BlockBase {
  type: 'table'
  columns: string[]
  rows: string[][]
  caption: string
}

export interface ComparisonBlock extends BlockBase {
  type: 'comparison'
  options: string[]
  criteria: string[]
  scores: (number | null)[][]
  notes: string[]
  verdict: string
}

export interface BoardBlock extends BlockBase {
  type: 'board'
  layout: 'grid' | 'columns'
  columns_count: number
  cells: { title: string; subtitle: string; items: { label: string; detail: string; tag: string }[] }[]
}

export interface MatrixBlock extends BlockBase {
  type: 'matrix'
  x_axis: string
  y_axis: string
  x_low: string
  x_high: string
  y_low: string
  y_high: string
  points: { label: string; x: number; y: number; highlight: boolean }[]
}

export interface DiagramBlock extends BlockBase {
  type: 'diagram'
  mermaid: string
  fallback: string
}

export interface TimelineBlock extends BlockBase {
  type: 'timeline'
  phases: { label: string; start: string; end: string; items: string[] }[]
}

export interface ListBlock extends BlockBase {
  type: 'list'
  style: 'bullets' | 'numbered' | 'checklist'
  items: { label: string; detail: string; rating: Level | null; tag: string }[]
}

export type Block =
  | AnswerBlock
  | TextBlock
  | StatsBlock
  | ChartBlock
  | TableBlock
  | ComparisonBlock
  | BoardBlock
  | MatrixBlock
  | DiagramBlock
  | TimelineBlock
  | ListBlock

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface AnalysisStep {
  id: string
  title: string
  objective: string
  status: StepStatus
  summary: string
  blocks: Block[]
  depends_on: string[]
  error: string | null
}

// Fields beyond `language`/`goal`/`steps` appear once the plan is ready
// (title, rationale, ...) or once the run completes (answer, findings, ...).
export interface AnalysisReport {
  language?: string
  goal?: string
  title?: string
  rationale?: string
  frameworks?: string[]
  key_questions?: string[]
  method_sources?: Citation[]
  steps?: AnalysisStep[]
  answer?: { headline: string; body: string; confidence: Level }
  findings?: string[]
  recommendations?: string[]
  sources?: Citation[]
}

export type StudyRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface StudyResultResponse {
  id: string
  project_id: string
  status: StudyRunStatus
  title: string | null
  goal: string | null
  report: AnalysisReport
  error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

// ── Analysis SSE events (every payload carries study_id) ─────────────────────

export interface StudyStartedPayload {
  study_id: string
  goal: string
}

export interface AnalysisPlanReadyPayload {
  study_id: string
  title: string
  steps: { id: string; title: string }[]
}

export interface AnalysisStepPayload {
  study_id: string
  step_id: string
  title: string
  status?: StepStatus
}

export interface StudyCompletedPayload {
  study_id: string
  status: StudyRunStatus
  title: string | null
}
