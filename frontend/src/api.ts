import type {
  BusinessProfile,
  ChatMessageRecord,
  ChatSessionRecord,
  MemoryEntry,
  ProjectSummary,
  StartStudyRequest,
} from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8007'

// FastAPI error bodies are {"detail": "..." | {...}} — prefer that over dumping
// the raw response body, which reads as a broken page rather than a message.
async function errorMessageFor(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // not JSON — fall through to the generic status-based message
  }
  return `Request failed (HTTP ${res.status}).`
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const res = await fetch(`${BASE}/api/projects`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ProjectSummary[]
}

// Thrown when project creation hard-blocks on a specific field (currently only
// pricing_unit_price) — carries the field name so the UI can surface the error
// inline next to that field instead of a generic message.
export class FieldError extends Error {
  field: string

  constructor(field: string, reason: string) {
    super(reason)
    this.field = field
  }
}

export async function getBusinessProfile(projectId: string): Promise<BusinessProfile> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/business-profile`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as BusinessProfile
}

export async function createProject(payload: StartStudyRequest): Promise<string> {
  const res = await fetch(`${BASE}/api/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (res.status === 422) {
    const body = (await res.json()) as { detail?: { field?: string; reason?: string } }
    throw new FieldError(body.detail?.field ?? 'unknown', body.detail?.reason ?? 'Validation failed.')
  }
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  const data = (await res.json()) as { project_id: string }
  return data.project_id
}

export async function listChatSessions(projectId: string): Promise<ChatSessionRecord[]> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/chat/sessions`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ChatSessionRecord[]
}

export async function createChatSession(projectId: string): Promise<ChatSessionRecord> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/chat/sessions`, { method: 'POST' })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ChatSessionRecord
}

export async function listChatMessages(
  projectId: string,
  sessionId: string,
): Promise<ChatMessageRecord[]> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/messages`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ChatMessageRecord[]
}

export async function listMemory(): Promise<MemoryEntry[]> {
  const res = await fetch(`${BASE}/api/memory`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as MemoryEntry[]
}

export async function addMemoryEntry(content: string): Promise<MemoryEntry> {
  const res = await fetch(`${BASE}/api/memory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as MemoryEntry
}

export async function deleteMemoryEntry(memoryId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/memory/${memoryId}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
}

export interface ChatSSEEvent {
  event: string
  data: unknown
}

// The chat endpoint is a POST that streams an SSE response body — EventSource
// can't send a POST body, so this reads the fetch response stream directly
// and parses the standard SSE "event: ...\ndata: ...\n\n" framing by hand.
export async function* streamChatMessage(
  projectId: string,
  sessionId: string,
  content: string,
): AsyncGenerator<ChatSSEEvent> {
  const res = await fetch(
    `${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    },
  )
  if (!res.ok || !res.body) {
    throw new Error(await errorMessageFor(res))
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function parseBlock(block: string): ChatSSEEvent | null {
    const lines = block.split(/\r?\n/)
    const eventLine = lines.find((line) => line.startsWith('event:'))
    const dataLine = lines.find((line) => line.startsWith('data:'))
    if (!eventLine || !dataLine) return null // e.g. ": ping" keep-alive comments, or blank
    const event = eventLine.slice('event:'.length).trim()
    const data = JSON.parse(dataLine.slice('data:'.length).trim())
    return { event, data }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (value) {
      buffer += decoder.decode(value, { stream: true })
      // sse-starlette separates messages with "\r\n\r\n" (CRLF), not plain
      // "\n\n" — splitting on a bare "\n\n" never matches, so every chunk
      // just accumulated into `buffer` and only the fallback flush below
      // (on `done`) ever ran, surfacing just the *first* event of the whole
      // stream. Match either line-ending style.
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() ?? ''
      for (const block of blocks) {
        const parsed = parseBlock(block)
        if (parsed) yield parsed
      }
    }
    if (done) {
      // The connection can close right after the final event without a
      // trailing blank line — flush whatever's left in the buffer instead of
      // silently dropping it (this was losing the last event of every turn,
      // e.g. chat_message_completed on simple no-tool-call replies).
      const parsed = parseBlock(buffer)
      if (parsed) yield parsed
      break
    }
  }
}
