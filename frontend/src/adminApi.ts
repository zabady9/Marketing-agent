// Client for the /api/admin/* raw-data-management API — no auth headers
// (the app has none anywhere; the admin panel ships unprotected, see
// AdminLayout's warning banner). Follows api.ts's conventions: one exported
// function per endpoint, typed Promise returns, errorMessageFor reused as-is.

import type {
  AdminListParams,
  ChatMessageAdminResponse,
  ChatMessageAdminUpdate,
  ChatSessionAdminResponse,
  ChatSessionAdminUpdate,
  GlossaryCacheAdminResponse,
  GlossaryCacheAdminUpdate,
  MemoryEntryAdminResponse,
  MemoryEntryAdminUpdate,
  PagedResult,
  ProjectAdminResponse,
  ProjectAdminUpdate,
  StudyResultAdminCreate,
  StudyResultAdminResponse,
  StudyResultAdminUpdate,
} from './adminTypes'
import type { BusinessProfile } from './types'
import type { BusinessProfileUpdate } from './adminTypes'

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8007'

// FastAPI error bodies are {"detail": "..." | [{loc,msg,type}, ...]} — a 422
// validation error's detail is an array of field errors, not a string; join
// their messages into one readable line instead of falling through to the
// generic "Request failed" message.
async function errorMessageFor(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      const messages = body.detail
        .map((item: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : undefined
          return field ? `${field}: ${item.msg}` : item.msg
        })
        .filter(Boolean)
      if (messages.length > 0) return messages.join('; ')
    }
  } catch {
    // not JSON — fall through to the generic status-based message
  }
  return `Request failed (HTTP ${res.status}).`
}

// Thrown on any 404 from the admin API — distinguishes "no such row" from a
// generic network/server failure so callers can show a dedicated not-found
// state instead of a retry button.
export class AdminNotFoundError extends Error {}

function buildQuery(params?: AdminListParams): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (res.status === 404) {
    throw new AdminNotFoundError(await errorMessageFor(res))
  }
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as T
}

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

// ── Project ──────────────────────────────────────────────────────────────────

export function listAdminProjects(
  params?: AdminListParams & { status?: string },
): Promise<PagedResult<ProjectAdminResponse>> {
  return request(`/api/admin/projects${buildQuery(params)}`)
}

export function getAdminProject(projectId: string): Promise<ProjectAdminResponse> {
  return request(`/api/admin/projects/${projectId}`)
}

export function updateAdminProject(
  projectId: string,
  payload: ProjectAdminUpdate,
): Promise<ProjectAdminResponse> {
  return patchJson(`/api/admin/projects/${projectId}`, payload)
}

export function softDeleteAdminProject(projectId: string): Promise<ProjectAdminResponse> {
  return del(`/api/admin/projects/${projectId}`)
}

export function restoreAdminProject(projectId: string): Promise<ProjectAdminResponse> {
  return postJson(`/api/admin/projects/${projectId}/restore`)
}

// ── BusinessProfile (nested, read/update only) ───────────────────────────────

export function getAdminBusinessProfile(projectId: string): Promise<BusinessProfile> {
  return request(`/api/admin/projects/${projectId}/business-profile`)
}

export function updateAdminBusinessProfile(
  projectId: string,
  payload: BusinessProfileUpdate,
): Promise<BusinessProfile> {
  return patchJson(`/api/admin/projects/${projectId}/business-profile`, payload)
}

// ── StudyResult ──────────────────────────────────────────────────────────────

export function listAdminStudies(
  params?: AdminListParams & { project_id?: string; status?: string; verdict?: string },
): Promise<PagedResult<StudyResultAdminResponse>> {
  return request(`/api/admin/studies${buildQuery(params)}`)
}

export function getAdminStudy(studyId: string): Promise<StudyResultAdminResponse> {
  return request(`/api/admin/studies/${studyId}`)
}

export function createAdminStudy(
  payload: StudyResultAdminCreate,
): Promise<StudyResultAdminResponse> {
  return postJson(`/api/admin/studies`, payload)
}

export function updateAdminStudy(
  studyId: string,
  payload: StudyResultAdminUpdate,
): Promise<StudyResultAdminResponse> {
  return patchJson(`/api/admin/studies/${studyId}`, payload)
}

export function softDeleteAdminStudy(studyId: string): Promise<StudyResultAdminResponse> {
  return del(`/api/admin/studies/${studyId}`)
}

export function restoreAdminStudy(studyId: string): Promise<StudyResultAdminResponse> {
  return postJson(`/api/admin/studies/${studyId}/restore`)
}

// ── ChatSession ──────────────────────────────────────────────────────────────

export function listAdminChatSessions(
  params?: AdminListParams & { project_id?: string },
): Promise<PagedResult<ChatSessionAdminResponse>> {
  return request(`/api/admin/chat-sessions${buildQuery(params)}`)
}

export function getAdminChatSession(sessionId: string): Promise<ChatSessionAdminResponse> {
  return request(`/api/admin/chat-sessions/${sessionId}`)
}

export function updateAdminChatSession(
  sessionId: string,
  payload: ChatSessionAdminUpdate,
): Promise<ChatSessionAdminResponse> {
  return patchJson(`/api/admin/chat-sessions/${sessionId}`, payload)
}

export function softDeleteAdminChatSession(sessionId: string): Promise<ChatSessionAdminResponse> {
  return del(`/api/admin/chat-sessions/${sessionId}`)
}

export function restoreAdminChatSession(sessionId: string): Promise<ChatSessionAdminResponse> {
  return postJson(`/api/admin/chat-sessions/${sessionId}/restore`)
}

// ── ChatMessage ──────────────────────────────────────────────────────────────

export function listAdminChatMessages(
  params?: AdminListParams & { session_id?: string; role?: string },
): Promise<PagedResult<ChatMessageAdminResponse>> {
  return request(`/api/admin/chat-messages${buildQuery(params)}`)
}

export function getAdminChatMessage(messageId: string): Promise<ChatMessageAdminResponse> {
  return request(`/api/admin/chat-messages/${messageId}`)
}

export function updateAdminChatMessage(
  messageId: string,
  payload: ChatMessageAdminUpdate,
): Promise<ChatMessageAdminResponse> {
  return patchJson(`/api/admin/chat-messages/${messageId}`, payload)
}

export function softDeleteAdminChatMessage(messageId: string): Promise<ChatMessageAdminResponse> {
  return del(`/api/admin/chat-messages/${messageId}`)
}

export function restoreAdminChatMessage(messageId: string): Promise<ChatMessageAdminResponse> {
  return postJson(`/api/admin/chat-messages/${messageId}/restore`)
}

// ── MemoryEntry ──────────────────────────────────────────────────────────────

export function listAdminMemoryEntries(
  params?: AdminListParams,
): Promise<PagedResult<MemoryEntryAdminResponse>> {
  return request(`/api/admin/memory${buildQuery(params)}`)
}

export function getAdminMemoryEntry(memoryId: string): Promise<MemoryEntryAdminResponse> {
  return request(`/api/admin/memory/${memoryId}`)
}

export function updateAdminMemoryEntry(
  memoryId: string,
  payload: MemoryEntryAdminUpdate,
): Promise<MemoryEntryAdminResponse> {
  return patchJson(`/api/admin/memory/${memoryId}`, payload)
}

export function softDeleteAdminMemoryEntry(memoryId: string): Promise<MemoryEntryAdminResponse> {
  return del(`/api/admin/memory/${memoryId}`)
}

export function restoreAdminMemoryEntry(memoryId: string): Promise<MemoryEntryAdminResponse> {
  return postJson(`/api/admin/memory/${memoryId}/restore`)
}

// ── GlossaryCache (keyed by `language`, not `id`) ────────────────────────────

export function listAdminGlossaryCache(
  params?: AdminListParams,
): Promise<PagedResult<GlossaryCacheAdminResponse>> {
  return request(`/api/admin/glossary${buildQuery(params)}`)
}

export function getAdminGlossaryCache(language: string): Promise<GlossaryCacheAdminResponse> {
  return request(`/api/admin/glossary/${language}`)
}

export function updateAdminGlossaryCache(
  language: string,
  payload: GlossaryCacheAdminUpdate,
): Promise<GlossaryCacheAdminResponse> {
  return patchJson(`/api/admin/glossary/${language}`, payload)
}

export function softDeleteAdminGlossaryCache(language: string): Promise<GlossaryCacheAdminResponse> {
  return del(`/api/admin/glossary/${language}`)
}

export function restoreAdminGlossaryCache(language: string): Promise<GlossaryCacheAdminResponse> {
  return postJson(`/api/admin/glossary/${language}/restore`)
}
