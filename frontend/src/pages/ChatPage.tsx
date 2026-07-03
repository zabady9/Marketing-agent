import { useCallback, useEffect, useRef, useState } from 'react'
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
import type { ChatMessage, ChatSession, ChatSessionDetail } from '../types'

const BASE = import.meta.env.VITE_API_URL ?? ''

interface ActiveTool {
  name: string
}

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

  const esRef = useRef<EventSource | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!wsId) return
    listChatSessions(wsId).then(setSessions).catch(() => {})
  }, [wsId])

  useEffect(() => {
    if (!wsId || !sessionId) {
      setDetail(null)
      return
    }
    getChatSession(wsId, sessionId).then(setDetail).catch(() => {})
  }, [wsId, sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [detail?.messages, streamingContent])

  const openStream = useCallback(
    (sid: string) => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      setStreamingContent('')
      setActiveTools([])
      setIsStreaming(true)

      const es = new EventSource(`${BASE}/api/workspaces/${wsId}/chat/sessions/${sid}/stream`)
      esRef.current = es

      es.onmessage = (e) => {
        let event: Record<string, unknown>
        try {
          event = JSON.parse(e.data)
        } catch {
          return
        }

        if (event.type === 'token') {
          setStreamingContent((prev) => prev + (event.content as string))
        } else if (event.type === 'tool_start') {
          setActiveTools((prev) => [...prev, { name: event.tool as string }])
        } else if (event.type === 'tool_end') {
          setActiveTools((prev) => prev.filter((t) => t.name !== event.tool))
        } else if (event.type === 'done' || event.type === 'error') {
          es.close()
          esRef.current = null
          setIsStreaming(false)
          setStreamingContent('')
          setActiveTools([])
          if (wsId && sid) {
            getChatSession(wsId, sid).then((d) => {
              setDetail(d)
              listChatSessions(wsId).then(setSessions).catch(() => {})
            })
          }
        }
      }

      es.onerror = () => {
        es.close()
        esRef.current = null
        setIsStreaming(false)
        setStreamingContent('')
        setActiveTools([])
      }
    },
    [wsId]
  )

  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  async function handleNewChat() {
    if (!wsId) return
    try {
      const session = await createChatSession(wsId)
      setSessions((prev) => [session, ...prev])
      navigate(`/workspaces/${wsId}/chat/${session.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فشل إنشاء الجلسة')
    }
  }

  async function handleDeleteSession(sid: string) {
    if (!wsId) return
    try {
      await deleteChatSession(wsId, sid)
      setSessions((prev) => prev.filter((s) => s.id !== sid))
      if (sessionId === sid) {
        navigate(`/workspaces/${wsId}/chat`)
        setDetail(null)
      }
    } catch {
      // ignore
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    if (!wsId || !sessionId || !input.trim() || sending) return

    const content = input.trim()
    setInput('')
    setSending(true)
    setError('')

    try {
      await sendChatMessage(wsId, sessionId, content)
      openStream(sessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فشل إرسال الرسالة')
    } finally {
      setSending(false)
    }
  }

  async function handleSubmitDraft(postId: string) {
    try {
      await submitDraftPost(postId)
      if (wsId && sessionId) {
        getChatSession(wsId, sessionId).then(setDetail)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'فشل إرسال المسودة')
    }
  }

  const messages: ChatMessage[] = detail?.messages ?? []

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">المساعد الذكي</span>
      </header>

      <div className="flex flex-1 overflow-hidden" style={{ height: 'calc(100vh - 60px)' }}>
        {/* Sidebar */}
        <aside className="w-64 bg-white border-l border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-100">
            <button
              onClick={handleNewChat}
              className="w-full bg-indigo-600 text-white text-sm font-medium py-2 px-4 rounded-lg hover:bg-indigo-700 transition-colors"
            >
              + محادثة جديدة
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 && (
              <p className="text-xs text-gray-400 px-4 py-6 text-center">لا توجد محادثات بعد</p>
            )}
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`group flex items-center gap-2 px-4 py-3 cursor-pointer border-b border-gray-50 hover:bg-gray-50 ${
                  s.id === sessionId ? 'bg-indigo-50 border-r-2 border-r-indigo-500' : ''
                }`}
                onClick={() => navigate(`/workspaces/${wsId}/chat/${s.id}`)}
              >
                <button
                  onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.id) }}
                  className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs px-1"
                  title="حذف"
                >
                  ✕
                </button>
                <span className="flex-1 text-sm text-gray-700 truncate">
                  {s.title || 'محادثة جديدة'}
                </span>
              </div>
            ))}
          </div>
        </aside>

        {/* Main chat area */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {!sessionId ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <div className="text-4xl mb-4">💬</div>
                <h2 className="text-xl font-semibold text-gray-800 mb-2">مساعد التسويق الذكي</h2>
                <p className="text-gray-500 text-sm mb-6">اطرح أسئلة عن علامتك التجارية، ابتكر المحتوى، أنشئ مسودات، أو ابدأ خطة.</p>
                <button
                  onClick={handleNewChat}
                  className="bg-indigo-600 text-white text-sm font-medium py-2 px-6 rounded-lg hover:bg-indigo-700 transition-colors"
                >
                  ابدأ محادثة
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    onSubmitDraft={handleSubmitDraft}
                  />
                ))}

                {/* Streaming assistant message */}
                {isStreaming && (
                  <div className="flex justify-start">
                    <div className="max-w-2xl bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
                      {activeTools.length > 0 && (
                        <div className="flex flex-wrap gap-2 mb-2">
                          {activeTools.map((t) => (
                            <span
                              key={t.name}
                              className="text-xs bg-indigo-50 text-indigo-600 border border-indigo-200 rounded-full px-2 py-0.5 animate-pulse"
                            >
                              {t.name.replace(/_/g, ' ')}…
                            </span>
                          ))}
                        </div>
                      )}
                      {streamingContent ? (
                        <MarkdownContent content={streamingContent} />
                      ) : (
                        <span className="text-sm text-gray-400 animate-pulse">جارٍ التفكير…</span>
                      )}
                    </div>
                  </div>
                )}

                {error && (
                  <p className="text-xs text-red-500 text-center">{error}</p>
                )}
                <div ref={bottomRef} />
              </div>

              {/* Input */}
              <form
                onSubmit={handleSend}
                className="px-6 py-4 border-t border-gray-200 bg-white flex gap-3 items-end"
              >
                <button
                  type="submit"
                  disabled={sending || isStreaming || !input.trim()}
                  className="bg-indigo-600 text-white text-sm font-medium px-5 py-2.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  إرسال
                </button>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSend(e as unknown as React.FormEvent)
                    }
                  }}
                  placeholder="اكتب رسالة… (Enter للإرسال، Shift+Enter لسطر جديد)"
                  rows={2}
                  className="flex-1 resize-none rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  disabled={sending || isStreaming}
                />
              </form>
            </>
          )}
        </main>
      </div>
    </div>
  )
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="text-sm text-gray-800 mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="text-base font-bold text-gray-900 mb-2 mt-3 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-sm font-bold text-gray-900 mb-2 mt-3 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-800 mb-1 mt-2 first:mt-0">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc list-inside text-sm text-gray-800 mb-2 space-y-0.5 pr-2">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside text-sm text-gray-800 mb-2 space-y-0.5 pr-2">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-gray-700">{children}</em>,
        code: ({ children, className }) => {
          const isBlock = className?.startsWith('language-')
          return isBlock
            ? <code className="block bg-gray-100 rounded-lg px-3 py-2 text-xs font-mono text-gray-700 mb-2 whitespace-pre-wrap overflow-x-auto">{children}</code>
            : <code className="bg-gray-100 rounded px-1 py-0.5 text-xs font-mono text-gray-700">{children}</code>
        },
        pre: ({ children }) => <pre className="mb-2">{children}</pre>,
        blockquote: ({ children }) => <blockquote className="border-r-4 border-indigo-300 pr-3 text-sm text-gray-600 italic mb-2">{children}</blockquote>,
        hr: () => <hr className="border-gray-200 my-3" />,
        a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline hover:text-indigo-800">{children}</a>,
        table: ({ children }) => <div className="overflow-x-auto mb-2"><table className="text-xs border-collapse w-full">{children}</table></div>,
        th: ({ children }) => <th className="border border-gray-300 bg-gray-50 px-2 py-1 text-right font-semibold text-gray-700">{children}</th>,
        td: ({ children }) => <td className="border border-gray-300 px-2 py-1 text-right text-gray-700">{children}</td>,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

function MessageBubble({
  message,
  onSubmitDraft,
}: {
  message: ChatMessage
  onSubmitDraft: (postId: string) => void
}) {
  const isUser = message.role === 'user'
  const draftPostId = message.metadata_?.draft_post_id as string | undefined

  return (
    <div className={`flex ${isUser ? 'justify-start' : 'justify-end'}`}>
      <div
        className={`max-w-2xl rounded-2xl px-4 py-3 shadow-sm ${
          isUser
            ? 'bg-indigo-600 text-white'
            : 'bg-white border border-gray-200 text-gray-800'
        }`}
      >
        {isUser
          ? <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          : <MarkdownContent content={message.content} />
        }
        {draftPostId && (
          <button
            onClick={() => onSubmitDraft(draftPostId)}
            className="mt-2 text-xs bg-white text-indigo-700 border border-indigo-300 rounded-full px-3 py-1 hover:bg-indigo-50 transition-colors"
          >
            إرسال للموافقة
          </button>
        )}
      </div>
    </div>
  )
}
