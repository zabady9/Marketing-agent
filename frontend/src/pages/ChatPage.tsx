import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { createChatSession, listChatMessages, listChatSessions, streamChatMessage } from '../api'
import type {
  ChatMessageCompletedPayload,
  ChatMessageRecord,
  ChatRole,
  ChatSessionRecord,
  ChatToolErrorPayload,
  CompetitiveLandscapeData,
  ExecutiveSummaryData,
  FinancialFeasibilityData,
  MarketOverviewData,
  RiskAssessmentData,
} from '../types'

type TranscriptItem =
  | { kind: 'message'; id: string; role: ChatRole; content: string; toolName?: string | null }
  | { kind: 'tool_error'; toolName: string; error: string }
  | { kind: 'section'; section: string; data: unknown }

function historyToTranscript(messages: ChatMessageRecord[]): TranscriptItem[] {
  return messages.map((m) => ({
    kind: 'message',
    id: m.id,
    role: m.role,
    content: m.content,
    toolName: m.tool_name,
  }))
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

function SectionCard({ section, data }: { section: string; data: unknown }) {
  if (section === 'market_overview') {
    const d = data as MarketOverviewData
    return (
      <SectionCardShell title="Market Overview">
        <div className="grid grid-cols-3 gap-3 text-center">
          <Stat label="TAM" value={fmt(d.tam.value)} unit={d.tam.currency} />
          <Stat label="SAM" value={fmt(d.sam.value)} unit={d.sam.currency} />
          <Stat label="SOM" value={fmt(d.som.value)} unit={d.som.currency} />
        </div>
        {d.narrative?.text && <p className="mt-3 text-xs text-gray-600">{d.narrative.text}</p>}
      </SectionCardShell>
    )
  }

  if (section === 'competitive_landscape') {
    const d = data as CompetitiveLandscapeData
    return (
      <SectionCardShell title="Competitive Landscape">
        <p className="text-xs text-gray-600">
          {d.competitors.length} competitor{d.competitors.length === 1 ? '' : 's'} analyzed
          {d.competitors.length > 0 && ': ' + d.competitors.map((c) => c.name).join(', ')}
        </p>
        {d.key_differentiators.length > 0 && (
          <ul className="mt-2 list-disc list-inside text-xs text-gray-600 space-y-0.5">
            {d.key_differentiators.slice(0, 3).map((diff, i) => (
              <li key={i}>{diff}</li>
            ))}
          </ul>
        )}
      </SectionCardShell>
    )
  }

  if (section === 'financial_feasibility') {
    const d = data as FinancialFeasibilityData
    return (
      <SectionCardShell title="Financial Feasibility">
        <div className="grid grid-cols-3 gap-3 text-center">
          <Stat label="Break-even" value={fmt(d.break_even_months.value)} unit="months" />
          <Stat label="ROI Year 1" value={fmt(d.roi_year_1.value)} unit="%" />
          <Stat
            label="NPV"
            value={fmt(d.npv.value)}
            unit={d.npv.is_positive ? 'positive' : 'negative'}
          />
        </div>
      </SectionCardShell>
    )
  }

  if (section === 'risk_assessment') {
    const d = data as RiskAssessmentData
    return (
      <SectionCardShell title="Risk Assessment">
        <p className="text-xs text-gray-600">
          {d.high_critical_count} high/critical risk{d.high_critical_count === 1 ? '' : 's'}{' '}
          identified out of {d.risks.length} total.
        </p>
        {d.risks.length > 0 && (
          <ul className="mt-2 list-disc list-inside text-xs text-gray-600 space-y-0.5">
            {d.risks.slice(0, 3).map((r, i) => (
              <li key={i}>{r.risk_description}</li>
            ))}
          </ul>
        )}
      </SectionCardShell>
    )
  }

  if (section === 'executive_summary') {
    const d = data as ExecutiveSummaryData
    return (
      <SectionCardShell title="Executive Summary">
        <p className="text-sm font-semibold text-gray-900">
          Verdict: <span className="uppercase">{d.verdict.replace(/_/g, ' ')}</span> · confidence{' '}
          {Math.round(d.confidence_score * 100)}%
        </p>
        {d.key_opportunities.length > 0 && (
          <div className="mt-2">
            <p className="text-xs font-medium text-gray-500">Opportunities</p>
            <ul className="list-disc list-inside text-xs text-gray-600 space-y-0.5">
              {d.key_opportunities.slice(0, 2).map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          </div>
        )}
        {d.key_risks.length > 0 && (
          <div className="mt-2">
            <p className="text-xs font-medium text-gray-500">Risks</p>
            <ul className="list-disc list-inside text-xs text-gray-600 space-y-0.5">
              {d.key_risks.slice(0, 2).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </SectionCardShell>
    )
  }

  return null
}

function SectionCardShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 px-4 py-3 max-w-md">
      <p className="text-xs font-semibold text-indigo-700 mb-2">{title}</p>
      {children}
    </div>
  )
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <p className="text-sm font-semibold text-gray-900">{value}</p>
      <p className="text-[10px] text-gray-500">
        {label}
        {unit ? ` (${unit})` : ''}
      </p>
    </div>
  )
}

function MessageBubble({ item }: { item: TranscriptItem & { kind: 'message' } }) {
  if (item.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-md rounded-lg bg-indigo-600 text-white px-4 py-2.5 text-sm">
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
      <div className="max-w-md rounded-lg bg-white border border-gray-200 px-4 py-2.5 text-sm text-gray-900 whitespace-pre-wrap">
        {item.content}
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
  const [transcript, setTranscript] = useState<TranscriptItem[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [progressLabel, setProgressLabel] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

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
    return () => {
      cancelled = true
    }
  }, [projectId])

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

  async function handleSend() {
    if (!projectId || !sessionId || !input.trim() || isSending) return
    const content = input.trim()
    const wasFirstMessage = !transcript.some((item) => item.kind === 'message' && item.role === 'user')
    setInput('')
    setSendError(null)
    setTranscript((prev) => [
      ...prev,
      { kind: 'message', id: `local-${Date.now()}`, role: 'user', content },
    ])
    setIsSending(true)

    try {
      for await (const evt of streamChatMessage(projectId, sessionId, content)) {
        if (evt.event === 'chat_tool_error') {
          const payload = evt.data as ChatToolErrorPayload
          setTranscript((prev) => [
            ...prev,
            { kind: 'tool_error', toolName: payload.tool_name, error: payload.error },
          ])
        } else if (evt.event === 'section_ready') {
          const payload = evt.data as { section: string; data: unknown }
          setTranscript((prev) => [
            ...prev,
            { kind: 'section', section: payload.section, data: payload.data },
          ])
          setProgressLabel(null)
        } else if (evt.event === 'chat_message_completed') {
          const payload = evt.data as ChatMessageCompletedPayload
          setTranscript((prev) => [
            ...prev,
            {
              kind: 'message',
              id: payload.message_id ?? `local-${Date.now()}`,
              role: payload.role,
              content: payload.content,
            },
          ])
          setProgressLabel(null)
        } else if (evt.event === 'agent_started') {
          const payload = evt.data as { agent: string }
          setProgressLabel(`Running ${payload.agent}…`)
        } else if (evt.event === 'agent_completed') {
          const payload = evt.data as { agent: string }
          setProgressLabel(`${payload.agent} completed`)
        }
      }
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to send message.')
    } finally {
      setIsSending(false)
      setProgressLabel(null)
      if (wasFirstMessage && projectId) {
        listChatSessions(projectId).then(setSessions).catch(() => {})
      }
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <div className="border-b border-gray-200 bg-white px-4 py-3 flex items-center justify-between">
        <Link
          to={`/projects/${projectId}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← Business profile
        </Link>
        <p className="text-sm font-medium text-gray-700">Chat</p>
        <Link to="/memory" className="text-sm text-gray-500 hover:text-gray-700">
          Manage memory
        </Link>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-56 shrink-0 border-r border-gray-200 bg-white overflow-y-auto px-3 py-4 hidden sm:block">
          <button
            onClick={handleNewChat}
            className="w-full mb-3 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
          >
            + New chat
          </button>
          <ul className="space-y-1">
            {sessions.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/projects/${projectId}/chat/${s.id}`}
                  className={`block rounded-md px-2.5 py-2 text-xs truncate transition-colors ${
                    s.id === sessionId
                      ? 'bg-indigo-50 border border-indigo-300 text-indigo-900'
                      : 'border border-transparent text-gray-600 hover:bg-gray-50'
                  }`}
                  title={s.title ?? 'New chat'}
                >
                  {s.title ?? 'New chat'}
                </Link>
              </li>
            ))}
          </ul>
        </aside>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-4 py-6">
            <div className="max-w-2xl mx-auto space-y-3">
              {loadingHistory && <p className="text-sm text-gray-400">Loading conversation…</p>}
              {historyError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {historyError}
                </div>
              )}
              {!loadingHistory && !historyError && transcript.length === 0 && (
                <p className="text-sm text-gray-400">
                  No messages yet. Ask the assistant to build a feasibility study for this project.
                </p>
              )}
              {transcript.map((item, i) => {
                if (item.kind === 'message') return <MessageBubble key={i} item={item} />
                if (item.kind === 'tool_error') {
                  return <ToolErrorBubble key={i} toolName={item.toolName} error={item.error} />
                }
                return (
                  <div key={i} className="flex justify-start">
                    <SectionCard section={item.section} data={item.data} />
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

          <div className="border-t border-gray-200 bg-white px-4 py-4">
            <div className="max-w-2xl mx-auto flex gap-2">
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
                disabled={isSending || !input.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSending ? 'Sending…' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
