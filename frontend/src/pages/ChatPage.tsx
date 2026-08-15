import { Component, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessage,
  submitDraftPost,
} from '../api'
import type { ChatMessage, ChatSession, ChatSessionDetail, ConsultVisuals } from '../types'
import VisualRenderer from '../components/VisualRenderer'

const BASE = import.meta.env.VITE_API_URL ?? ''

// ── agent persona registry ────────────────────────────────────────────────────
interface AgentInfo { name: string; role: string; avatarBg: string }

const AGENT_PERSONAS: Record<string, AgentInfo> = {
  strategist:     { name: 'Sam',    role: 'Strategist',     avatarBg: 'bg-indigo-500' },
  copywriter:     { name: 'Alex',   role: 'Copywriter',     avatarBg: 'bg-purple-500' },
  seo_analyst:    { name: 'Jordan', role: 'SEO Analyst',    avatarBg: 'bg-green-500'  },
  brand_guardian: { name: 'Morgan', role: 'Brand Guardian', avatarBg: 'bg-amber-500'  },
  chief_of_staff: { name: 'Casey',  role: 'Chief of Staff', avatarBg: 'bg-slate-500'  },
}

// ── types ─────────────────────────────────────────────────────────────────────
interface ActiveTool { name: string; agent?: string }
interface LiveAgentMessage { agentId: string; agentName: string; content: string }
interface CurrentAgent { id: string; name: string; bidReason: string }
type MeetingPhase = 'idle' | 'bidding' | 'speaking' | 'synthesis' | 'concluded'

// Group persisted messages so a meeting's team discussion + synthesis render together.
type MessageGroup =
  | { type: 'single'; message: ChatMessage }
  | { type: 'meeting'; teamTurns: ChatMessage[]; synthesis: ChatMessage | null }

function groupMessages(messages: ChatMessage[]): MessageGroup[] {
  const groups: MessageGroup[] = []
  let i = 0
  while (i < messages.length) {
    const msg = messages[i]
    if (msg.meeting_id) {
      const mid = msg.meeting_id
      const batch: ChatMessage[] = []
      while (i < messages.length && messages[i].meeting_id === mid) {
        batch.push(messages[i++])
      }
      groups.push({
        type: 'meeting',
        teamTurns: batch.filter(m => m.agent_id !== 'chief_of_staff'),
        synthesis: batch.find(m => m.agent_id === 'chief_of_staff') ?? null,
      })
    } else {
      groups.push({ type: 'single', message: msg })
      i++
    }
  }
  return groups
}

// ── error boundary (prevents a chart crash from unmounting the whole page) ────
class MessagesErrorBoundary extends Component<
  { children: React.ReactNode },
  { crashed: boolean; errorMsg: string }
> {
  state = { crashed: false, errorMsg: '' }
  static getDerivedStateFromError(error: Error) {
    return { crashed: true, errorMsg: error?.message ?? '' }
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[MessagesErrorBoundary] render crash:', error, info.componentStack)
  }
  render() {
    if (this.state.crashed) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sm text-gray-400">
          <p>حدث خطأ أثناء عرض المحادثة.</p>
          <button
            onClick={() => this.setState({ crashed: false, errorMsg: '' })}
            className="text-xs text-indigo-500 underline"
          >
            إعادة المحاولة
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ── main component ────────────────────────────────────────────────────────────
export default function ChatPage() {
  const { wsId, sessionId } = useParams<{ wsId: string; sessionId?: string }>()
  const navigate = useNavigate()

  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [detail, setDetail] = useState<ChatSessionDetail | null>(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [activeTools, setActiveTools] = useState<ActiveTool[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const [currentAgent, setCurrentAgent] = useState<CurrentAgent | null>(null)
  const [meetingPhase, setMeetingPhase] = useState<MeetingPhase>('idle')
  const [liveAgentMessages, setLiveAgentMessages] = useState<LiveAgentMessage[]>([])

  const [visualsByMessageId, setVisualsByMessageId] = useState<Record<string, ConsultVisuals>>({})
  const [generatingVisualsForMessageId, setGeneratingVisualsForMessageId] = useState<string | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const currentStreamRef = useRef('')
  const currentAgentRef = useRef<CurrentAgent | null>(null)
  // Holds the ID of the last committed assistant message so the visuals event
  // handler can attach to the correct message even if the user sends a new
  // message between `done` and `visuals` arriving.
  const lastCommittedMessageIdRef = useRef<string | null>(null)
  // Buffers a visuals payload that arrived before lastCommittedMessageIdRef was set.
  // Flushed in the done handler once the message ID is resolved.
  const pendingVisualsRef = useRef<ConsultVisuals | null>(null)
  // True when visuals_generating arrived before getChatSession resolved.
  // Flushed in the done handler alongside lastCommittedMessageIdRef.
  const pendingVisualsGeneratingRef = useRef(false)
  // Safety-net timer: if stream_complete never arrives after done, close after 35s.
  const streamCompleteTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!wsId) return
    listChatSessions(wsId).then(setSessions).catch(() => {})
  }, [wsId])

  useEffect(() => {
    if (!wsId || !sessionId) { setDetail(null); return }
    getChatSession(wsId, sessionId).then(setDetail).catch(() => {})
  }, [wsId, sessionId])

  useEffect(() => {
    if (!detail) return
    const fromMeta: Record<string, ConsultVisuals> = {}
    for (const msg of detail.messages) {
      const v = msg.metadata_?.visuals
      if (Array.isArray(v) && v.length > 0) {
        fromMeta[msg.id] = {
          visuals: v as ConsultVisuals['visuals'],
          sources: (msg.metadata_?.sources as ConsultVisuals['sources']) ?? [],
        }
      }
    }
    if (Object.keys(fromMeta).length > 0) {
      // Metadata is the baseline; live SSE visuals (already in state) take precedence.
      setVisualsByMessageId(prev => ({ ...fromMeta, ...prev }))
    }
  }, [detail])

  useEffect(() => {
    const el = scrollContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [detail?.messages, streamingContent, liveAgentMessages])

  const resetStreamState = () => {
    setIsStreaming(false); setStreamingContent(''); setActiveTools([])
    setCurrentAgent(null); setMeetingPhase('idle'); setLiveAgentMessages([])
    currentStreamRef.current = ''; currentAgentRef.current = null
  }

  const openStream = useCallback((sid: string) => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    setStreamingContent(''); setActiveTools([]); setIsStreaming(true)
    setCurrentAgent(null); setMeetingPhase('idle'); setLiveAgentMessages([])
    currentStreamRef.current = ''; currentAgentRef.current = null
    pendingVisualsRef.current = null
    setGeneratingVisualsForMessageId(null)

    const es = new EventSource(`${BASE}/api/workspaces/${wsId}/chat/sessions/${sid}/stream`)
    esRef.current = es

    es.onmessage = (e) => {
      let ev: Record<string, unknown>
      try { ev = JSON.parse(e.data) } catch { return }

      if (ev.type === 'token') {
        const text = ev.content as string
        currentStreamRef.current += text
        setStreamingContent(prev => prev + text)

      } else if (ev.type === 'tool_start') {
        setActiveTools(prev => [...prev, { name: ev.tool as string, agent: ev.agent as string | undefined }])

      } else if (ev.type === 'tool_end') {
        setActiveTools(prev => prev.filter(t => !(t.name === ev.tool && t.agent === ev.agent)))

      } else if (ev.type === 'bidding_start') {
        setMeetingPhase('bidding'); setCurrentAgent(null); currentAgentRef.current = null

      } else if (ev.type === 'agent_turn_start') {
        const agent: CurrentAgent = { id: ev.agent as string, name: ev.name as string, bidReason: ev.bid_reason as string }
        setMeetingPhase('speaking'); setCurrentAgent(agent); currentAgentRef.current = agent
        currentStreamRef.current = ''; setStreamingContent('')

      } else if (ev.type === 'agent_turn_end') {
        const agent = currentAgentRef.current; const content = currentStreamRef.current
        if (agent && content) setLiveAgentMessages(prev => [...prev, { agentId: agent.id, agentName: agent.name, content }])
        currentStreamRef.current = ''; setStreamingContent('')

      } else if (ev.type === 'meeting_concluded') {
        setMeetingPhase('concluded')

      } else if (ev.type === 'synthesis_start') {
        const agent: CurrentAgent = { id: 'chief_of_staff', name: 'Casey', bidReason: '' }
        setMeetingPhase('synthesis'); setCurrentAgent(agent); currentAgentRef.current = agent
        currentStreamRef.current = ''; setStreamingContent('')

      } else if (ev.type === 'synthesis_end') {
        const content = currentStreamRef.current
        if (content) setLiveAgentMessages(prev => [...prev, { agentId: 'chief_of_staff', agentName: 'Casey', content }])
        currentStreamRef.current = ''

      } else if (ev.type === 'done') {
        // Text is ready — commit message bubble but keep connection open.
        // Capture the message ID from the session fetch so the visuals event
        // can attach to the right message even if the user sends another message
        // before stream_complete arrives.
        if (wsId && sid) {
          getChatSession(wsId, sid).then(d => {
            setDetail(d)
            // Identify the last assistant message just committed.
            const msgs = d?.messages ?? []
            const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant')
            lastCommittedMessageIdRef.current = lastAssistant?.id ?? null
            // Flush buffered visuals_generating that arrived before this ref was set.
            if (pendingVisualsGeneratingRef.current && lastAssistant?.id) {
              setGeneratingVisualsForMessageId(lastAssistant.id)
              pendingVisualsGeneratingRef.current = false
            }
            // Flush visuals that arrived before the ref was set (race condition buffer).
            if (pendingVisualsRef.current && lastAssistant?.id) {
              setVisualsByMessageId(prev => ({
                ...prev,
                [lastAssistant.id]: pendingVisualsRef.current!,
              }))
              pendingVisualsRef.current = null
            }
          }).catch(() => {})
        }
        // Safety net: if stream_complete never arrives (network drop after done),
        // close after 35s — longer than the backend's 30s visual-generation timeout
        // so we don't race it under normal conditions.
        if (streamCompleteTimeoutRef.current) clearTimeout(streamCompleteTimeoutRef.current)
        streamCompleteTimeoutRef.current = setTimeout(() => {
          es.close(); esRef.current = null
          resetStreamState()
          if (wsId && sid) listChatSessions(wsId).then(setSessions).catch(() => {})
        }, 35_000)

      } else if (ev.type === 'visuals_generating') {
        const msgId = lastCommittedMessageIdRef.current
        if (msgId) setGeneratingVisualsForMessageId(msgId)
        else pendingVisualsGeneratingRef.current = true

      } else if (ev.type === 'visuals') {
        setGeneratingVisualsForMessageId(null)
        try {
          const payload = JSON.parse(e.data) as ConsultVisuals
          const msgId = lastCommittedMessageIdRef.current
          if (msgId) {
            setVisualsByMessageId(prev => ({ ...prev, [msgId]: payload }))
          } else {
            pendingVisualsRef.current = payload  // buffer until done handler sets the ref
          }
        } catch { /* malformed visuals payload — ignore */ }

      } else if (ev.type === 'stream_complete') {
        // Normal close signal from backend — clears the safety-net timer.
        setGeneratingVisualsForMessageId(null)
        if (streamCompleteTimeoutRef.current) clearTimeout(streamCompleteTimeoutRef.current)
        es.close(); esRef.current = null
        resetStreamState()
        if (wsId && sid) listChatSessions(wsId).then(setSessions).catch(() => {})

      } else if (ev.type === 'error') {
        // Error close path — no stream_complete expected.
        if (streamCompleteTimeoutRef.current) clearTimeout(streamCompleteTimeoutRef.current)
        es.close(); esRef.current = null
        if (wsId && sid) {
          getChatSession(wsId, sid).then(d => {
            setDetail(d)
            resetStreamState()
            listChatSessions(wsId).then(setSessions).catch(() => {})
          }).catch(() => resetStreamState())
        } else {
          resetStreamState()
        }
      }
    }
    es.onerror = () => { es.close(); esRef.current = null; resetStreamState() }
  }, [wsId])

  useEffect(() => {
    return () => {
      esRef.current?.close()
      if (streamCompleteTimeoutRef.current) clearTimeout(streamCompleteTimeoutRef.current)
    }
  }, [])

  async function handleNewChat() {
    if (!wsId) return
    try {
      const session = await createChatSession(wsId)
      setSessions(prev => [session, ...prev])
      navigate(`/workspaces/${wsId}/chat/${session.id}`)
    } catch (err) { setError(err instanceof Error ? err.message : 'فشل إنشاء الجلسة') }
  }

  async function handleDeleteSession(sid: string) {
    if (!wsId) return
    try {
      await deleteChatSession(wsId, sid)
      setSessions(prev => prev.filter(s => s.id !== sid))
      if (sessionId === sid) { navigate(`/workspaces/${wsId}/chat`); setDetail(null) }
    } catch { /* ignore */ }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId || !sessionId || !input.trim() || sending) return
    const content = input.trim()
    setInput(''); setSending(true); setError('')
    const tempMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      metadata_: {},
      agent_id: null,
      meeting_id: null,
      created_at: new Date().toISOString(),
    }
    setDetail(prev => prev ? { ...prev, messages: [...prev.messages, tempMsg] } : prev)
    try {
      await sendChatMessage(wsId, sessionId, content)
      openStream(sessionId)
    } catch (err) { setError(err instanceof Error ? err.message : 'فشل إرسال الرسالة') }
    finally { setSending(false) }
  }

  async function handleSubmitDraft(postId: string) {
    try {
      await submitDraftPost(postId)
      if (wsId && sessionId) getChatSession(wsId, sessionId).then(setDetail)
    } catch (err) { setError(err instanceof Error ? err.message : 'فشل إرسال المسودة') }
  }

  const groups = groupMessages(detail?.messages ?? [])

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">المساعد الذكي</span>
      </header>

      <div className="flex flex-1 overflow-hidden" style={{ height: 'calc(100vh - 60px)' }}>
        <aside className="w-64 bg-white border-l border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-100">
            <button onClick={handleNewChat} className="w-full bg-indigo-600 text-white text-sm font-medium py-2 px-4 rounded-lg hover:bg-indigo-700 transition-colors">
              + محادثة جديدة
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 && <p className="text-xs text-gray-400 px-4 py-6 text-center">لا توجد محادثات بعد</p>}
            {sessions.map(s => (
              <div
                key={s.id}
                className={`group flex items-center gap-2 px-4 py-3 cursor-pointer border-b border-gray-50 hover:bg-gray-50 ${s.id === sessionId ? 'bg-indigo-50 border-r-2 border-r-indigo-500' : ''}`}
                onClick={() => navigate(`/workspaces/${wsId}/chat/${s.id}`)}
              >
                <button onClick={e => { e.stopPropagation(); handleDeleteSession(s.id) }} className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs px-1" title="حذف">✕</button>
                <span className="flex-1 text-sm text-gray-700 truncate">{s.title || 'محادثة جديدة'}</span>
              </div>
            ))}
          </div>
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden">
          {!sessionId ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <div className="text-4xl mb-4">💬</div>
                <h2 className="text-xl font-semibold text-gray-800 mb-2">مساعد التسويق الذكي</h2>
                <p className="text-gray-500 text-sm mb-6">اطرح أسئلة عن علامتك التجارية، ابتكر المحتوى، أنشئ مسودات، أو ابدأ خطة.</p>
                <button onClick={handleNewChat} className="bg-indigo-600 text-white text-sm font-medium py-2 px-6 rounded-lg hover:bg-indigo-700 transition-colors">ابدأ محادثة</button>
              </div>
            </div>
          ) : (
            <>
              <MessagesErrorBoundary key={sessionId}>
              <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-6 space-y-4">
                {/* Persisted messages — meetings grouped as discussion + synthesis */}
                {groups.map((g, i) =>
                  g.type === 'single'
                    ? <MessageBubble key={g.message.id} message={g.message} onSubmitDraft={handleSubmitDraft} visuals={visualsByMessageId[g.message.id]} isGeneratingVisuals={generatingVisualsForMessageId === g.message.id} />
                    : <MeetingGroup key={i} teamTurns={g.teamTurns} synthesis={g.synthesis} onSubmitDraft={handleSubmitDraft} visualsByMessageId={visualsByMessageId} generatingVisualsForMessageId={generatingVisualsForMessageId} />
                )}

                {/* Live meeting: compact collapsible discussion panel */}
                {isStreaming && meetingPhase !== 'idle' && (
                  <LiveDiscussionPanel
                    phase={meetingPhase}
                    liveMessages={liveAgentMessages}
                    currentAgent={currentAgent}
                    streamingContent={meetingPhase === 'speaking' ? streamingContent : ''}
                    activeTools={activeTools}
                  />
                )}

                {/* Live synthesis: full-size main response */}
                {isStreaming && meetingPhase === 'synthesis' && (
                  <AssistantBubble>
                    <ToolBadges tools={activeTools} />
                    {streamingContent
                      ? <MarkdownContent content={streamingContent} />
                      : <span className="text-sm text-gray-400 animate-pulse">جارٍ التلخيص…</span>}
                  </AssistantBubble>
                )}

                {/* Regular single-agent streaming */}
                {isStreaming && meetingPhase === 'idle' && (
                  <AssistantBubble>
                    <ToolBadges tools={activeTools} />
                    {streamingContent
                      ? <MarkdownContent content={streamingContent} />
                      : <span className="text-sm text-gray-400 animate-pulse">جارٍ التفكير…</span>}
                  </AssistantBubble>
                )}

                {error && <p className="text-xs text-red-500 text-center">{error}</p>}
                <div />
              </div>
              </MessagesErrorBoundary>

              <form onSubmit={handleSend} className="px-6 py-4 border-t border-gray-200 bg-white">
                <div className="flex gap-3 items-end">
                  <button type="submit" disabled={sending || isStreaming || !input.trim()} className="bg-indigo-600 text-white text-sm font-medium px-5 py-2.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                    إرسال
                  </button>
                  <textarea
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(e as unknown as React.FormEvent) } }}
                    placeholder="اكتب رسالة… (Enter للإرسال، Shift+Enter لسطر جديد)"
                    rows={2}
                    className="flex-1 resize-none rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    disabled={sending || isStreaming}
                  />
                </div>
              </form>
            </>
          )}
        </main>
      </div>
    </div>
  )
}

// ── persisted meeting group ───────────────────────────────────────────────────

function MeetingGroup({ teamTurns, synthesis, onSubmitDraft, visualsByMessageId, generatingVisualsForMessageId }: {
  teamTurns: ChatMessage[]
  synthesis: ChatMessage | null
  onSubmitDraft: (id: string) => void
  visualsByMessageId: Record<string, ConsultVisuals>
  generatingVisualsForMessageId: string | null
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="space-y-2">
      {/* Collapsed team discussion — secondary, muted */}
      {teamTurns.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-gray-50 overflow-hidden text-xs">
          <button
            onClick={() => setExpanded(p => !p)}
            className="w-full flex items-center justify-between px-3 py-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <span>نقاش الفريق · {teamTurns.length} {teamTurns.length === 1 ? 'رد' : 'ردود'}</span>
            <span className="text-gray-300">{expanded ? '▲' : '▾'}</span>
          </button>
          {expanded && (
            <div className="px-3 pb-3 pt-1 space-y-3 border-t border-gray-100">
              {teamTurns.map(m => {
                const persona = AGENT_PERSONAS[m.agent_id ?? '']
                return <CompactAgentTurn key={m.id} agentId={m.agent_id ?? ''} agentName={persona?.name ?? (m.agent_id ?? '')} content={m.content} />
              })}
            </div>
          )}
        </div>
      )}
      {/* Synthesis — primary response */}
      {synthesis && (
        <MessageBubble
          message={synthesis}
          onSubmitDraft={onSubmitDraft}
          visuals={visualsByMessageId[synthesis.id]}
          isGeneratingVisuals={generatingVisualsForMessageId === synthesis.id}
        />
      )}
    </div>
  )
}

// ── live discussion panel (during streaming) ──────────────────────────────────

function LiveDiscussionPanel({ phase, liveMessages, currentAgent, streamingContent, activeTools }: {
  phase: MeetingPhase
  liveMessages: LiveAgentMessage[]
  currentAgent: CurrentAgent | null
  streamingContent: string
  activeTools: ActiveTool[]
}) {
  const [expanded, setExpanded] = useState(true)

  // auto-collapse when the meeting ends or synthesis starts
  useEffect(() => {
    if (phase === 'concluded' || phase === 'synthesis') setExpanded(false)
  }, [phase])

  const isActive = phase === 'bidding' || phase === 'speaking'
  const totalTurns = liveMessages.length + (phase === 'speaking' && currentAgent ? 1 : 0)

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 overflow-hidden text-xs">
      <button
        onClick={() => setExpanded(p => !p)}
        className="w-full flex items-center justify-between px-3 py-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <span className="flex items-center gap-1.5">
          {isActive && <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />}
          {phase === 'bidding' && 'الفريق يقرر من يتحدث…'}
          {phase === 'speaking' && currentAgent && `${currentAgent.name} يتحدث…`}
          {(phase === 'concluded' || phase === 'synthesis') && `نقاش الفريق · ${totalTurns} ${totalTurns === 1 ? 'رد' : 'ردود'}`}
        </span>
        <span className="text-gray-300">{expanded ? '▲' : '▾'}</span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-3 border-t border-gray-100">
          {/* Committed turns */}
          {liveMessages.map((m, i) => (
            <CompactAgentTurn key={i} agentId={m.agentId} agentName={m.agentName} content={m.content} />
          ))}

          {/* Bidding dots */}
          {phase === 'bidding' && (
            <div className="flex items-center gap-1 text-gray-400 py-1">
              <span className="flex gap-0.5">
                <span className="w-1 h-1 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1 h-1 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1 h-1 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
              <span className="mr-1">تقييم المشاركة</span>
            </div>
          )}

          {/* Current agent streaming inline inside panel */}
          {phase === 'speaking' && currentAgent && (
            <div className="flex gap-2 items-start">
              <div className={`w-5 h-5 ${AGENT_PERSONAS[currentAgent.id]?.avatarBg ?? 'bg-gray-400'} rounded-full flex-shrink-0 flex items-center justify-center text-white font-bold mt-0.5`} style={{ fontSize: '10px' }}>
                {currentAgent.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-gray-500 font-medium mb-0.5">
                  {currentAgent.name}{AGENT_PERSONAS[currentAgent.id] ? ` · ${AGENT_PERSONAS[currentAgent.id].role}` : ''}
                  {currentAgent.bidReason && <span className="font-normal text-gray-400 mr-1">— {currentAgent.bidReason}</span>}
                </div>
                <ToolBadges tools={activeTools} compact />
                {streamingContent
                  ? <p className="text-gray-600 leading-relaxed whitespace-pre-wrap">{streamingContent}</p>
                  : <span className="text-gray-400 animate-pulse">جارٍ التفكير…</span>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── shared primitives ─────────────────────────────────────────────────────────

function CompactAgentTurn({ agentId, agentName, content }: { agentId: string; agentName: string; content: string }) {
  const persona = AGENT_PERSONAS[agentId]
  return (
    <div className="flex gap-2 items-start">
      <div className={`w-5 h-5 ${persona?.avatarBg ?? 'bg-gray-400'} rounded-full flex-shrink-0 flex items-center justify-center text-white font-bold mt-0.5`} style={{ fontSize: '10px' }}>
        {agentName[0]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-gray-500 mb-0.5">
          {agentName}{persona ? ` · ${persona.role}` : ''}
        </div>
        <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">{content}</p>
      </div>
    </div>
  )
}

function AssistantBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-2xl bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm text-gray-800">
        {children}
      </div>
    </div>
  )
}

function ToolBadges({ tools, compact }: { tools: ActiveTool[]; compact?: boolean }) {
  if (tools.length === 0) return null
  return (
    <div className={`flex flex-wrap gap-1.5 ${compact ? 'mb-1' : 'mb-2'}`}>
      {tools.map((t, i) => (
        <span key={i} className={`bg-indigo-50 text-indigo-600 border border-indigo-200 rounded-full animate-pulse ${compact ? 'text-xs px-1.5 py-px' : 'text-xs px-2 py-0.5'}`}>
          {t.name.replace(/_/g, ' ')}…
        </span>
      ))}
    </div>
  )
}

function MessageBubble({ message, onSubmitDraft, visuals, isGeneratingVisuals }: {
  message: ChatMessage
  onSubmitDraft: (id: string) => void
  visuals?: ConsultVisuals
  isGeneratingVisuals?: boolean
}) {
  const isUser = message.role === 'user'
  const draftPostId = message.metadata_?.draft_post_id as string | undefined

  if (isUser) {
    return (
      <div className="flex justify-start">
        <div className="max-w-2xl bg-indigo-600 text-white rounded-2xl px-4 py-3 shadow-sm">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    )
  }

  // synthesis or regular assistant — same prominent treatment
  return (
    <div className="flex justify-end">
      <div className="max-w-2xl w-full bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm text-gray-800">
        <MarkdownContent content={message.content} />
        {draftPostId && <DraftButton postId={draftPostId} onSubmit={onSubmitDraft} />}
        {visuals && visuals.visuals.length > 0 && (
          <VisualRenderer visuals={visuals.visuals} sources={visuals.sources} />
        )}
        {isGeneratingVisuals && !visuals && (
          <div className="mt-3 flex items-center gap-2 text-sm text-gray-400 animate-pulse">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>جارٍ توليد الرسوم البيانية…</span>
          </div>
        )}
      </div>
    </div>
  )
}

function DraftButton({ postId, onSubmit }: { postId: string; onSubmit: (id: string) => void }) {
  return (
    <button onClick={() => onSubmit(postId)} className="mt-2 text-xs bg-white text-indigo-700 border border-indigo-300 rounded-full px-3 py-1 hover:bg-indigo-50 transition-colors">
      إرسال للموافقة
    </button>
  )
}

function MarkdownContent({ content }: { content: string }) {
  if (!content) return null
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p:          ({ children }) => <p className="text-sm text-gray-800 mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1:         ({ children }) => <h1 className="text-base font-bold text-gray-900 mb-2 mt-3 first:mt-0">{children}</h1>,
        h2:         ({ children }) => <h2 className="text-sm font-bold text-gray-900 mb-2 mt-3 first:mt-0">{children}</h2>,
        h3:         ({ children }) => <h3 className="text-sm font-semibold text-gray-800 mb-1 mt-2 first:mt-0">{children}</h3>,
        ul:         ({ children }) => <ul className="list-disc list-inside text-sm text-gray-800 mb-2 space-y-0.5 pr-2">{children}</ul>,
        ol:         ({ children }) => <ol className="list-decimal list-inside text-sm text-gray-800 mb-2 space-y-0.5 pr-2">{children}</ol>,
        li:         ({ children }) => <li className="leading-relaxed">{children}</li>,
        strong:     ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
        em:         ({ children }) => <em className="italic text-gray-700">{children}</em>,
        pre:        ({ children }) => <pre className="mb-2">{children}</pre>,
        blockquote: ({ children }) => <blockquote className="border-r-4 border-indigo-300 pr-3 text-sm text-gray-600 italic mb-2">{children}</blockquote>,
        hr:         () => <hr className="border-gray-200 my-3" />,
        a:          ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline hover:text-indigo-800">{children}</a>,
        table:      ({ children }) => <div className="overflow-x-auto mb-2"><table className="text-xs border-collapse w-full">{children}</table></div>,
        th:         ({ children }) => <th className="border border-gray-300 bg-gray-50 px-2 py-1 text-right font-semibold text-gray-700">{children}</th>,
        td:         ({ children }) => <td className="border border-gray-300 px-2 py-1 text-right text-gray-700">{children}</td>,
        code: ({ children, className }) => {
          const isBlock = className?.startsWith('language-')
          return isBlock
            ? <code className="block bg-gray-100 rounded-lg px-3 py-2 text-xs font-mono text-gray-700 mb-2 whitespace-pre-wrap overflow-x-auto">{children}</code>
            : <code className="bg-gray-100 rounded px-1 py-0.5 text-xs font-mono text-gray-700">{children}</code>
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
