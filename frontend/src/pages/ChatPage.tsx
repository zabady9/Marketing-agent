import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  createChatSession,
  GenerationInProgressError,
  listChatMessages,
  listArtifacts,
  listChatSessions,
  listStudies,
  resumeChatMessageStream,
  streamChatMessage,
} from '../api'
import type { ChatSSEEvent } from '../api'
import { SectionCardShell } from '../components/report/primitives'
import { GenericChart } from '../components/report/charts/GenericChart'
import { ArtifactCard } from '../components/report/ArtifactCard'
import { AnalysisCard } from '../components/chat/AnalysisCard'
import { Markdown } from '../components/report/blocks/Markdown'
import { ChatSidebar } from '../components/chat/ChatSidebar'
import {
  PendingAttachmentChips,
  SentAttachmentChips,
  usePendingAttachments,
} from '../components/chat/attachments'
import type {
  ArtifactListItem,
  ArtifactSummary,
  AttachmentSummary,
  ChatArtifactReadyPayload,
  ChatChartReadyPayload,
  ChatMessageCompletedPayload,
  ChatMessageDeltaPayload,
  ChatMessageRecord,
  ChatRole,
  ChatSessionRecord,
  ChatToolErrorPayload,
  ChartSpec,
  StudyResultResponse,
} from '../types'

type TranscriptItem =
  | {
      kind: 'message'
      id: string
      role: ChatRole
      content: string
      toolName?: string | null
      streaming?: boolean
      attachments?: AttachmentSummary[]
    }
  | { kind: 'tool_error'; toolName: string; error: string }
  // One card per analysis run — keyed (and de-duplicated) by study id.
  | { kind: 'analysis'; studyId: string }
  | { kind: 'chart'; chart: ChartSpec; messageId: string }
  | { kind: 'artifact'; artifact: ArtifactSummary; messageId: string }

// The assistant's reply row is created when its turn starts, so in stored
// order it comes BEFORE the tool rows of that turn. Live, the reply streams in
// after the tools (cards) — reorder each turn so a reload looks the same.
function inTurnOrder(messages: ChatMessageRecord[]): ChatMessageRecord[] {
  const out: ChatMessageRecord[] = []
  let replies: ChatMessageRecord[] = []
  for (const m of messages) {
    if (m.role === 'user') {
      out.push(...replies)
      replies = []
      out.push(m)
    } else if (m.role === 'assistant') {
      replies.push(m)
    } else {
      out.push(m)
    }
  }
  return [...out, ...replies]
}

function historyToTranscript(messages: ChatMessageRecord[]): TranscriptItem[] {
  const items: TranscriptItem[] = []
  const seenStudies = new Set<string>()
  inTurnOrder(messages).forEach((m) => {
    if (m.role === 'tool' && m.study_id) {
      // The analysis card replaces the raw tool line, and appears once per run.
      if (!seenStudies.has(m.study_id)) {
        seenStudies.add(m.study_id)
        items.push({ kind: 'analysis', studyId: m.study_id })
      }
      return
    }
    items.push({
      kind: 'message',
      id: m.id,
      role: m.role,
      content: m.content,
      toolName: m.tool_name,
      attachments: m.attachments,
    })
    if (m.role === 'tool' && m.tool_name === 'generate_chart_tool' && m.chart_data) {
      items.push({ kind: 'chart', chart: m.chart_data, messageId: m.id })
    }
    if (m.role === 'tool' && m.artifact_data) {
      items.push({ kind: 'artifact', artifact: m.artifact_data, messageId: m.id })
    }
  })
  return items
}

function MessageBubble({ item }: { item: TranscriptItem & { kind: 'message' } }) {
  if (item.role === 'user') {
    return (
      <div className="flex justify-end">
        <div dir="auto" className="max-w-md rounded-lg bg-indigo-600 text-white px-4 py-2.5 text-sm whitespace-pre-wrap">
          {item.attachments && <SentAttachmentChips attachments={item.attachments} />}
          {item.content}
        </div>
      </div>
    )
  }
  if (item.role === 'tool') {
    return (
      <div className="flex justify-start">
        <div className="max-w-md rounded-lg bg-gray-100 text-gray-500 px-3 py-1.5 text-xs font-mono">
          🔧 {item.toolName}: {item.content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div dir="auto" className="max-w-xl rounded-lg bg-white border border-gray-200 px-4 py-2.5 text-sm text-gray-900">
        <Markdown text={item.content} />
      </div>
    </div>
  )
}

function ToolErrorBubble({ toolName, error }: { toolName: string; error: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-md rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
        ⚠ <span className="font-medium">{toolName}</span> failed: {error}
      </div>
    </div>
  )
}

export function ChatPage() {
  const { projectId, sessionId } = useParams<{ projectId: string; sessionId: string }>()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<ChatSessionRecord[]>([])
  const [studies, setStudies] = useState<StudyResultResponse[]>([])
  const [files, setFiles] = useState<ArtifactListItem[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [transcript, setTranscript] = useState<TranscriptItem[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [progressLabel, setProgressLabel] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const attachments = usePendingAttachments(projectId, sessionId)
  const canSend =
    !isSending && !attachments.busy && (input.trim().length > 0 || attachments.sendable.length > 0)
  // Per-run counter bumped on every live analysis event, so that run's card
  // refreshes immediately (cards also poll on their own while running).
  const [analysisBumps, setAnalysisBumps] = useState<Record<string, number>>({})
  // The stream belonging to the session on screen; aborted when the user
  // switches chats so one chat's events can never land in another.
  const streamAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort()
      streamAbortRef.current = null
    }
  }, [sessionId])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    listChatSessions(projectId)
      .then((data) => {
        if (cancelled) return
        setSessions(data)
      })
      .catch(() => {
        // Sidebar is a convenience — a failed fetch here shouldn't block the
        // main transcript from loading, so errors are swallowed.
      })
    listStudies(projectId)
      .then((data) => {
        if (cancelled) return
        setStudies(data)
      })
      .catch(() => {})
    listArtifacts(projectId)
      .then((data) => {
        if (cancelled) return
        setFiles(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [projectId])

  function refreshStudies() {
    if (!projectId) return
    listStudies(projectId).then(setStudies).catch(() => {})
  }

  function refreshFiles() {
    if (!projectId) return
    listArtifacts(projectId).then(setFiles).catch(() => {})
  }

  useEffect(() => {
    if (!projectId || !sessionId) return
    let cancelled = false
    setLoadingHistory(true)
    setHistoryError(null)
    listChatMessages(projectId, sessionId)
      .then((messages) => {
        if (cancelled) return
        setTranscript(historyToTranscript(messages))
        setLoadingHistory(false)

        // If the page was refreshed mid-generation, the last assistant row
        // is still "pending"/"streaming" — historyToTranscript already
        // rendered whatever text it has (so nothing generated is lost even
        // if the resume below fails), and this picks the live stream back
        // up in place.
        const lastMessage = messages[messages.length - 1]
        if (
          lastMessage &&
          lastMessage.role === 'assistant' &&
          (lastMessage.status === 'pending' || lastMessage.status === 'streaming')
        ) {
          attachToActiveGeneration(lastMessage)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setHistoryError(err instanceof Error ? err.message : 'Failed to load chat history.')
        setLoadingHistory(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript, progressLabel])

  async function handleNewChat() {
    if (!projectId) return
    const session = await createChatSession(projectId)
    setSessions((prev) => [session, ...prev])
    navigate(`/projects/${projectId}/chat/${session.id}`)
  }

  // Shared by a fresh send (streamChatMessage) and resuming an in-flight
  // generation after a refresh (resumeChatMessageStream) — both yield the
  // same event shapes, so the UI update logic doesn't need to know which one
  // is driving it.
  async function consumeChatEvents(stream: AsyncGenerator<ChatSSEEvent>) {
    for await (const evt of stream) {
      if (evt.event === 'chat_tool_error') {
        const payload = evt.data as ChatToolErrorPayload
        setTranscript((prev) => [
          ...prev,
          { kind: 'tool_error', toolName: payload.tool_name, error: payload.error },
        ])
      } else if (evt.event === 'study_started') {
        const { study_id } = evt.data as { study_id: string }
        setTranscript((prev) =>
          prev.some((item) => item.kind === 'analysis' && item.studyId === study_id)
            ? prev
            : [...prev, { kind: 'analysis', studyId: study_id }],
        )
        refreshStudies()
      } else if (
        evt.event === 'analysis_plan_ready' ||
        evt.event === 'analysis_step_completed' ||
        evt.event === 'study_completed'
      ) {
        const { study_id } = evt.data as { study_id: string }
        setAnalysisBumps((prev) => ({ ...prev, [study_id]: (prev[study_id] ?? 0) + 1 }))
        if (evt.event === 'study_completed') refreshStudies()
      } else if (evt.event === 'chat_chart_ready') {
        const payload = evt.data as ChatChartReadyPayload
        setTranscript((prev) => [
          ...prev,
          { kind: 'chart', chart: payload.chart, messageId: payload.message_id },
        ])
      } else if (evt.event === 'chat_artifact_ready') {
        const payload = evt.data as ChatArtifactReadyPayload
        setTranscript((prev) => [
          ...prev,
          { kind: 'artifact', artifact: payload.artifact, messageId: payload.message_id },
        ])
        refreshFiles()
      } else if (evt.event === 'chat_message_delta') {
        const payload = evt.data as ChatMessageDeltaPayload
        setTranscript((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.kind === 'message' && last.streaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + payload.content }]
          }
          return [
            ...prev,
            {
              kind: 'message',
              id: `streaming-${Date.now()}`,
              role: 'assistant',
              content: payload.content,
              streaming: true,
            },
          ]
        })
        setProgressLabel(null)
      } else if (evt.event === 'chat_message_completed') {
        const payload = evt.data as ChatMessageCompletedPayload
        setTranscript((prev) => {
          const finalMessage: TranscriptItem = {
            kind: 'message',
            id: payload.message_id ?? `local-${Date.now()}`,
            role: payload.role,
            content: payload.content,
          }
          const last = prev[prev.length - 1]
          if (last && last.kind === 'message' && last.streaming) {
            return [...prev.slice(0, -1), finalMessage]
          }
          return [...prev, finalMessage]
        })
        setProgressLabel(null)
      }
    }
  }

  // Re-attaches to a generation that's already running on the backend for
  // this session — used both when reload finds a message left mid-generation
  // (see the history-loading effect) and when a fresh send 409s because
  // another tab (or this tab's own prior attempt) is already generating one.
  async function attachToActiveGeneration(active: ChatMessageRecord) {
    if (!projectId || !sessionId) return
    setTranscript((prev) => {
      if (prev.some((item) => item.kind === 'message' && item.id === active.id)) {
        return prev.map((item) =>
          item.kind === 'message' && item.id === active.id ? { ...item, streaming: true } : item,
        )
      }
      return [
        ...prev,
        { kind: 'message', id: active.id, role: 'assistant', content: active.content, streaming: true },
      ]
    })
    setIsSending(true)
    const controller = new AbortController()
    streamAbortRef.current = controller
    try {
      await consumeChatEvents(
        resumeChatMessageStream(projectId, sessionId, active.id, active.content.length, controller.signal),
      )
    } catch (err) {
      if (controller.signal.aborted) return
      setSendError(err instanceof Error ? err.message : 'Failed to resume the in-progress reply.')
    } finally {
      if (!controller.signal.aborted) {
        setIsSending(false)
        setProgressLabel(null)
        refreshStudies()
      }
    }
  }

  async function handleSend() {
    if (!projectId || !sessionId || !canSend) return
    const content = input.trim()
    const sent = attachments.sendable.map((p) => p.attachment!)
    const wasFirstMessage = !transcript.some((item) => item.kind === 'message' && item.role === 'user')
    const localId = `local-${Date.now()}`
    setInput('')
    setSendError(null)
    setTranscript((prev) => [
      ...prev,
      { kind: 'message', id: localId, role: 'user', content, attachments: sent },
    ])
    setIsSending(true)
    const controller = new AbortController()
    streamAbortRef.current = controller

    try {
      const stream = streamChatMessage(
        projectId,
        sessionId,
        content,
        sent.map((a) => a.id),
        controller.signal,
      )
      // The request (and its 409/404 checks) only goes out on the first
      // next() — clear the chips once it's accepted, not before.
      const first = await stream.next()
      attachments.clearSent()
      await consumeChatEvents(
        (async function* () {
          if (!first.done) yield first.value
          yield* stream
        })(),
      )
    } catch (err) {
      // Switched to another chat: the generation keeps running server-side and
      // reappears (with its analysis cards) when the user comes back.
      if (controller.signal.aborted) return
      if (err instanceof GenerationInProgressError) {
        // The backend never accepted this turn — drop the optimistic bubble
        // and give the input back so the user can resend once the
        // already-running generation (another tab, or this tab reconnecting
        // after a refresh) finishes.
        setTranscript((prev) => prev.filter((item) => !(item.kind === 'message' && item.id === localId)))
        setInput(content)
        setSendError('A response is already being generated for this chat — showing its progress below.')
        try {
          const messages = await listChatMessages(projectId, sessionId)
          const active = [...messages]
            .reverse()
            .find((m) => m.role === 'assistant' && (m.status === 'pending' || m.status === 'streaming'))
          if (active) await attachToActiveGeneration(active)
        } catch {
          // Best-effort — the message above already explains the 409.
        }
      } else {
        setSendError(err instanceof Error ? err.message : 'Failed to send message.')
      }
    } finally {
      if (!controller.signal.aborted) {
        setIsSending(false)
        setProgressLabel(null)
        refreshStudies()
      }
      if (wasFirstMessage && projectId) {
        listChatSessions(projectId).then(setSessions).catch(() => {})
      }
    }
  }

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open chats and studies"
            className="sm:hidden rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-600 hover:bg-gray-50"
          >
            ☰
          </button>
          <Link
            to={`/projects/${projectId}`}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            ← Business profile
          </Link>
        </div>
        <p className="text-sm font-medium text-gray-700">Chat</p>
        <Link to="/memory" className="text-sm text-gray-500 hover:text-gray-700">
          Manage memory
        </Link>
      </div>

      <div className="flex-1 min-h-0 flex overflow-hidden">
        <ChatSidebar
          projectId={projectId}
          sessionId={sessionId}
          sessions={sessions}
          studies={studies}
          files={files}
          onFileDeleted={(id) => setFiles((prev) => prev.filter((f) => f.id !== id))}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onNewChat={handleNewChat}
        />

        <div
          className={`relative flex-1 min-h-0 flex flex-col overflow-hidden ${dragging ? 'ring-2 ring-inset ring-indigo-400' : ''}`}
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes('Files')) return
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={(e) => {
            if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
            setDragging(false)
          }}
          onDrop={(e) => {
            if (!e.dataTransfer.files.length) return
            e.preventDefault()
            setDragging(false)
            attachments.addFiles(e.dataTransfer.files)
          }}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-indigo-50/70 text-sm font-medium text-indigo-700">
              Drop files to attach
            </div>
          )}
          <div className="flex-1 min-h-0 overflow-y-auto px-4 py-6">
            <div className="max-w-2xl mx-auto space-y-3">
              {loadingHistory && <p className="text-sm text-gray-400">Loading conversation…</p>}
              {historyError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {historyError}
                </div>
              )}
              {!loadingHistory && !historyError && transcript.length === 0 && (
                <p className="text-sm text-gray-400">
                  No messages yet. Ask for any analysis: a feasibility study, a SWOT, or a question like "can I compete with the big players?"
                </p>
              )}
              {transcript.map((item, i) => {
                if (item.kind === 'message') return <MessageBubble key={i} item={item} />
                if (item.kind === 'tool_error') {
                  return <ToolErrorBubble key={i} toolName={item.toolName} error={item.error} />
                }
                if (item.kind === 'chart') {
                  return (
                    <div key={i} className="flex justify-start">
                      <SectionCardShell title={item.chart.title}>
                        <GenericChart chart={item.chart} compact />
                      </SectionCardShell>
                    </div>
                  )
                }
                if (item.kind === 'artifact') {
                  return (
                    <div key={i} className="flex justify-start">
                      <ArtifactCard projectId={projectId!} artifact={item.artifact} />
                    </div>
                  )
                }
                return (
                  <div key={`analysis-${item.studyId}`} className="flex justify-start">
                    <AnalysisCard projectId={projectId!} studyId={item.studyId} bump={analysisBumps[item.studyId] ?? 0} />
                  </div>
                )
              })}
              {progressLabel && (
                <div className="flex justify-start">
                  <div className="max-w-md rounded-lg bg-gray-50 border border-gray-200 px-3 py-1.5 text-xs text-gray-500 italic">
                    {progressLabel}
                  </div>
                </div>
              )}
              {sendError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {sendError}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-4">
            <PendingAttachmentChips pending={attachments.pending} onRemove={attachments.remove} />
            <div className="max-w-2xl mx-auto flex gap-2">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) attachments.addFiles(e.target.files)
                  e.target.value = ''
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isSending}
                title="Attach files (any type, up to 2 GB)"
                aria-label="Attach files"
                className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
              >
                📎
              </button>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder="Ask the assistant about this project…"
                disabled={isSending}
                className="flex-1 rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={!canSend}
                className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSending ? 'Sending…' : attachments.busy ? 'Uploading…' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
