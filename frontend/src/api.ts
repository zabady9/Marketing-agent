import type {
  ArtifactSummary,
  AttachmentSummary,
  BusinessProfile,
  ChatMessageRecord,
  ChatSessionRecord,
  MemoryEntry,
  ProjectSummary,
  StudyResultResponse,
  UploadTarget,
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

// Thrown specifically on a 404 (project exists, but chat hasn't built its
// business profile yet) so BusinessProfilePage can redirect into chat
// instead of showing a dead-end error for what's actually a normal state.
export class ProfileNotFoundError extends Error {}

export async function getBusinessProfile(projectId: string): Promise<BusinessProfile> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/business-profile`)
  if (res.status === 404) {
    throw new ProfileNotFoundError('Business profile not found')
  }
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as BusinessProfile
}

export async function getProject(projectId: string): Promise<ProjectSummary> {
  const res = await fetch(`${BASE}/api/projects/${projectId}`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ProjectSummary
}

// Thrown when a specific study id can't be found — distinguishes "no such
// study" (show an empty/not-found state) from a generic network/server
// failure (show a retry button) in the report page.
export class StudyNotFoundError extends Error {}

export async function listStudies(projectId: string): Promise<StudyResultResponse[]> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/studies`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as StudyResultResponse[]
}

export async function getStudyById(projectId: string, studyId: string): Promise<StudyResultResponse> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/studies/${studyId}`)
  if (res.status === 404) {
    throw new StudyNotFoundError(await errorMessageFor(res))
  }
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as StudyResultResponse
}

export async function exportStudyMarkdown(projectId: string, studyId: string): Promise<string> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/studies/${studyId}/export`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.text()
}

export async function exportChatMarkdown(
  projectId: string,
  sessionId: string,
  studyIds?: string[],
): Promise<string> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ study_ids: studyIds ?? null }),
  })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.text()
}

// Fetches a generated artifact's raw bytes as a Blob — the first binary
// (non-text) fetch in this file; every other export helper above reads
// `res.text()`. Callers build the download filename from the ArtifactSummary
// they already have (title + format) rather than parsing Content-Disposition,
// since the browser's `download` attribute on the anchor element is what
// actually names the saved file, not the response header.
export async function downloadChatArtifact(projectId: string, artifact: ArtifactSummary): Promise<Blob> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/chat/artifacts/${artifact.id}/download`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.blob()
}

function attachmentsUrl(projectId: string, sessionId: string): string {
  return `${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/attachments`
}

// Step 1 of an upload: registers the file and returns where to PUT its
// bytes. Files go straight to storage (GCS in production), never through
// the backend's request body — see app/routers/attachments.py.
export async function createAttachment(
  projectId: string,
  sessionId: string,
  file: File,
): Promise<{ attachment: AttachmentSummary; upload: UploadTarget }> {
  const res = await fetch(attachmentsUrl(projectId, sessionId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type,
      size_bytes: file.size,
    }),
  })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.json()
}

// Step 2: XMLHttpRequest rather than fetch, since fetch has no upload
// progress events (and these files can be up to 2 GB).
export function uploadToTarget(
  target: UploadTarget,
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(target.method, target.url)
    Object.entries(target.headers).forEach(([k, v]) => xhr.setRequestHeader(k, v))
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload failed (HTTP ${xhr.status}).`))
    xhr.onerror = () => reject(new Error('Upload failed — check your connection.'))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort())
    xhr.send(file)
  })
}

// Step 3: tells the backend the bytes are in place; processing (text
// extraction / Gemini upload) then runs in the background — poll
// getAttachment until status is "ready" or "failed".
export async function completeAttachment(
  projectId: string,
  sessionId: string,
  attachmentId: string,
): Promise<AttachmentSummary> {
  const res = await fetch(`${attachmentsUrl(projectId, sessionId)}/${attachmentId}/complete`, {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.json()
}

export async function getAttachment(
  projectId: string,
  sessionId: string,
  attachmentId: string,
): Promise<AttachmentSummary> {
  const res = await fetch(`${attachmentsUrl(projectId, sessionId)}/${attachmentId}`)
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return res.json()
}

export async function deleteAttachment(
  projectId: string,
  sessionId: string,
  attachmentId: string,
): Promise<void> {
  const res = await fetch(`${attachmentsUrl(projectId, sessionId)}/${attachmentId}`, {
    method: 'DELETE',
  })
  if (!res.ok && res.status !== 404) {
    throw new Error(await errorMessageFor(res))
  }
}

export async function createProject(): Promise<string> {
  const res = await fetch(`${BASE}/api/projects`, { method: 'POST' })
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

export async function getChatMessage(
  projectId: string,
  sessionId: string,
  messageId: string,
): Promise<ChatMessageRecord> {
  const res = await fetch(
    `${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/messages/${messageId}`,
  )
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  return (await res.json()) as ChatMessageRecord
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

// Thrown when the POST endpoint 409s because a generation is already running
// for this session (e.g. another tab is mid-turn, or this tab reconnected
// after a refresh while its own prior generation is still in flight).
export class GenerationInProgressError extends Error {}

// Reads a fetch Response's body as the standard SSE "event: ...\ndata:
// ...\n\n" framing and yields parsed events — shared by both the POST chat
// endpoint (streamChatMessage) and the GET resume-stream endpoint
// (resumeChatMessageStream), since EventSource can't be used for either
// (POST can't carry a body; the resume stream is opened programmatically
// alongside other fetches, not as a page-level EventSource).
async function* consumeSSEStream(res: Response): AsyncGenerator<ChatSSEEvent> {
  if (!res.body) {
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

// The chat endpoint is a POST that streams an SSE response body — EventSource
// can't send a POST body, so this reads the fetch response stream directly.
export async function* streamChatMessage(
  projectId: string,
  sessionId: string,
  content: string,
  attachmentIds: string[] = [],
): AsyncGenerator<ChatSSEEvent> {
  const res = await fetch(
    `${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, attachment_ids: attachmentIds }),
    },
  )
  if (!res.ok) {
    const message = await errorMessageFor(res)
    // A 409 can also mean an attachment isn't sendable (still processing /
    // already sent) — only the in-flight-generation one triggers resume.
    if (res.status === 409 && message.includes('already being generated')) {
      throw new GenerationInProgressError(message)
    }
    throw new Error(message)
  }
  yield* consumeSSEStream(res)
}

// Re-attaches to a generation already in flight on the backend (e.g. after a
// page refresh) — polls the persisted message server-side and re-emits the
// same chat_message_delta/chat_message_completed shape streamChatMessage
// does, so callers can consume both identically. `alreadyHaveLength` is the
// length of content the caller already rendered (e.g. from a prior
// listChatMessages/getChatMessage call) — only the delta beyond that is
// streamed back, so already-shown text isn't duplicated.
export async function* resumeChatMessageStream(
  projectId: string,
  sessionId: string,
  messageId: string,
  alreadyHaveLength: number,
): AsyncGenerator<ChatSSEEvent> {
  const res = await fetch(
    `${BASE}/api/projects/${projectId}/chat/sessions/${sessionId}/messages/${messageId}/stream` +
      `?after=${alreadyHaveLength}`,
  )
  if (!res.ok) {
    throw new Error(await errorMessageFor(res))
  }
  yield* consumeSSEStream(res)
}
