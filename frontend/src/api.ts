import type { AnalysisSubject, ChatSession, ChatSessionDetail, KnowledgeChunk, KnowledgeDocument, Report, Workspace } from './types'

const BASE = import.meta.env.VITE_API_URL ?? ''
const ADMIN_KEY = import.meta.env.VITE_ADMIN_API_KEY ?? ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData
  const extraHeaders: Record<string, string> = {}
  if (!isFormData) extraHeaders['Content-Type'] = 'application/json'
  if (path.startsWith('/api/admin') && ADMIN_KEY) extraHeaders['X-Admin-Key'] = ADMIN_KEY
  const res = await fetch(`${BASE}${path}`, {
    headers: { ...extraHeaders, ...(init?.headers as Record<string, string> | undefined) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// Workspaces
export const listWorkspaces = () => req<Workspace[]>('/api/workspaces')
export const createWorkspace = (name: string) =>
  req<Workspace>('/api/workspaces', { method: 'POST', body: JSON.stringify({ name }) })

// Analysis Subject
export const getAnalysisSubject = (wsId: string) =>
  req<AnalysisSubject>(`/api/workspaces/${wsId}/analysis-subject`).catch(() => null)
export const updateAnalysisSubject = (wsId: string, data: Partial<AnalysisSubject>) =>
  req<AnalysisSubject>(`/api/workspaces/${wsId}/analysis-subject`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })

// Knowledge documents
export const uploadDocument = (wsId: string, file: File, docType = 'other') => {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  return req<KnowledgeDocument>(`/api/workspaces/${wsId}/knowledge/documents`, {
    method: 'POST',
    body: form,
  })
}
export const listDocuments = (wsId: string) =>
  req<KnowledgeDocument[]>(`/api/workspaces/${wsId}/knowledge/documents`)
export const deleteDocument = (wsId: string, docId: string) =>
  req<void>(`/api/workspaces/${wsId}/knowledge/documents/${docId}`, { method: 'DELETE' })
export const searchKnowledge = (wsId: string, q: string, k = 5) =>
  req<KnowledgeChunk[]>(
    `/api/workspaces/${wsId}/knowledge/search?q=${encodeURIComponent(q)}&k=${k}`
  )

// Reports
export const listReports = (wsId: string) =>
  req<Report[]>(`/api/workspaces/${wsId}/reports`)
export const getReport = (wsId: string, reportId: string) =>
  req<Report>(`/api/workspaces/${wsId}/reports/${reportId}`)
export const generateReport = (wsId: string, analysisType: string, context?: string) =>
  req<Report>(`/api/workspaces/${wsId}/reports:generate`, {
    method: 'POST',
    body: JSON.stringify({ analysis_type: analysisType, context: context ?? null }),
  })

// Chat
export const createChatSession = (wsId: string, title?: string) =>
  req<ChatSession>(`/api/workspaces/${wsId}/chat/sessions`, {
    method: 'POST',
    body: JSON.stringify({ title: title ?? null }),
  })
export const listChatSessions = (wsId: string) =>
  req<ChatSession[]>(`/api/workspaces/${wsId}/chat/sessions`)
export const getChatSession = (wsId: string, sessionId: string) =>
  req<ChatSessionDetail>(`/api/workspaces/${wsId}/chat/sessions/${sessionId}`)
export const deleteChatSession = (wsId: string, sessionId: string) =>
  req<void>(`/api/workspaces/${wsId}/chat/sessions/${sessionId}`, { method: 'DELETE' })
export const sendChatMessage = (wsId: string, sessionId: string, content: string) =>
  req<{ message_id: string; meeting_id?: string }>(
    `/api/workspaces/${wsId}/chat/sessions/${sessionId}/messages`,
    { method: 'POST', body: JSON.stringify({ content }) }
  )

// Admin
export interface AdminStats {
  workspaces: number
  action_logs: number
  [key: string]: number
}
export interface AdminLog {
  id: string; workspace_id: string; actor: string; action: string
  payload: Record<string, unknown>; result: Record<string, unknown> | null; created_at: string
}

export const adminStats = () => req<AdminStats>('/api/admin/stats')
export const adminWorkspaces = () => req<{ id: string; name: string; autonomy_level: string; created_at: string }[]>('/api/admin/workspaces')
export const adminDeleteWorkspace = (id: string) => req<void>(`/api/admin/workspaces/${id}`, { method: 'DELETE' })
export const adminLogs = (limit = 100, offset = 0) => req<AdminLog[]>(`/api/admin/logs?limit=${limit}&offset=${offset}`)
