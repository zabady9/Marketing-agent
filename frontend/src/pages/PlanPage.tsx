import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getPlan } from '../api'
import type { Plan, Post } from '../types'
import PostCard from '../components/PostCard'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001'

const STATUS_COLOR: Record<string, string> = {
  generating: 'bg-yellow-100 text-yellow-700',
  ready: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

const STATUS_LABEL: Record<string, string> = {
  generating: 'جارٍ التوليد',
  ready: 'جاهز',
  failed: 'فشل',
}

const POST_STATUS_LABEL: Record<string, string> = {
  pending_approval: 'في الانتظار',
  approved: 'مُعتمد',
  scheduled: 'مُجدول',
  published: 'منشور',
  rejected: 'مرفوض',
}

const POST_STATUS_COLOR: Record<string, string> = {
  pending_approval: 'text-yellow-600',
  approved: 'text-green-600',
  scheduled: 'text-blue-600',
  published: 'text-purple-600',
  rejected: 'text-red-500',
}

interface StreamLine {
  type: string
  message?: string
  day?: number
  theme?: string
  format?: string
  content?: string
  hashtags?: string[]
  issues?: string[]
  ideas?: { day: number; theme: string; format: string }[]
}

export default function PlanPage() {
  const { wsId, planId } = useParams<{ wsId: string; planId: string }>()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [streamLines, setStreamLines] = useState<StreamLine[]>([])
  const [streaming, setStreaming] = useState(false)
  const terminalRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  function updatePost(updated: Post) {
    setPlan(p => p ? { ...p, posts: p.posts.map(post => post.id === updated.id ? updated : post) } : p)
  }

  function deletePost(postId: string) {
    setPlan(p => p ? { ...p, posts: p.posts.filter(post => post.id !== postId) } : p)
  }

  const addLine = useCallback((line: StreamLine) => {
    setStreamLines(prev => [...prev, line])
    setTimeout(() => {
      terminalRef.current?.scrollTo({ top: terminalRef.current.scrollHeight, behavior: 'smooth' })
    }, 30)
  }, [])

  const startStream = useCallback(() => {
    if (!wsId || !planId || esRef.current) return
    setStreaming(true)
    const es = new EventSource(`${API}/api/workspaces/${wsId}/plans/${planId}/stream`)
    esRef.current = es

    es.onmessage = async (e) => {
      const event: StreamLine & { plan_id?: string } = JSON.parse(e.data)

      if (event.type === 'ping') return

      addLine(event)

      if (event.type === 'done') {
        es.close()
        esRef.current = null
        setStreaming(false)
        if (wsId && planId) {
          const p = await getPlan(wsId, planId)
          setPlan(p)
        }
      }

      if (event.type === 'error') {
        es.close()
        esRef.current = null
        setStreaming(false)
        if (wsId && planId) {
          const p = await getPlan(wsId, planId)
          setPlan(p)
        }
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      setStreaming(false)
    }
  }, [wsId, planId, addLine])

  useEffect(() => {
    if (!wsId || !planId) return

    getPlan(wsId, planId).then(p => {
      setPlan(p)
      setLoading(false)
      if (p.status === 'generating') {
        startStream()
      }
    }).catch(() => {
      setError('تعذّر تحميل الخطة')
      setLoading(false)
    })

    return () => {
      esRef.current?.close()
      esRef.current = null
    }
  }, [wsId, planId, startStream])

  if (loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-gray-400 text-sm">جارٍ التحميل…</div>
    </div>
  )

  if (error || !plan) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-red-500 text-sm">{error || 'الخطة غير موجودة'}</div>
    </div>
  )

  const pending = plan.posts.filter(p => p.status === 'pending_approval').length
  const approved = plan.posts.filter(p => p.status === 'approved').length
  const scheduled = plan.posts.filter(p => p.status === 'scheduled').length
  const published = plan.posts.filter(p => p.status === 'published').length
  const rejected = plan.posts.filter(p => p.status === 'rejected').length

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white px-8 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center font-bold text-sm">م</div>
        <Link to="/" className="text-slate-400 hover:text-white text-sm transition-colors">مساحات العمل</Link>
        <span className="text-slate-600">/</span>
        <Link to={`/workspaces/${wsId}`} className="text-slate-400 hover:text-white text-sm transition-colors">مساحة العمل</Link>
        <span className="text-slate-600">/</span>
        <span className="text-sm font-medium">الخطة</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {/* Plan header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-sm text-gray-400">{new Date(plan.created_at).toLocaleDateString('ar-SA')}</span>
            <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_COLOR[plan.status] ?? 'bg-gray-100 text-gray-600'}`}>
              {plan.status === 'generating' ? '⏳ جارٍ التوليد…' : (STATUS_LABEL[plan.status] ?? plan.status)}
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">{plan.goal || 'تعزيز الوعي بالعلامة التجارية'}</h1>

          {plan.status === 'ready' && (
            <div className="flex gap-4 mt-4 text-sm">
              {[
                { label: 'pending_approval', count: pending },
                { label: 'approved', count: approved },
                { label: 'scheduled', count: scheduled },
                { label: 'published', count: published },
                { label: 'rejected', count: rejected },
              ].filter(s => s.count > 0).map(s => (
                <span key={s.label} className={`font-medium ${POST_STATUS_COLOR[s.label]}`}>{s.count} {POST_STATUS_LABEL[s.label]}</span>
              ))}
            </div>
          )}

          {plan.status === 'failed' && (
            <div className="mt-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              فشل التوليد: {plan.error}
            </div>
          )}
        </div>

        {/* Live stream terminal */}
        {(streaming || streamLines.length > 0) && (
          <div className="mb-8 bg-slate-950 rounded-xl overflow-hidden shadow-xl">
            <div className="px-4 py-2.5 bg-slate-900 flex items-center gap-2 border-b border-slate-800">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <div className="w-3 h-3 rounded-full bg-yellow-500" />
                <div className="w-3 h-3 rounded-full bg-green-500" />
              </div>
              <span className="text-slate-400 text-xs mr-2 font-mono">سجل التوليد</span>
              {streaming && (
                <span className="mr-auto flex items-center gap-1.5 text-xs text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  مباشر
                </span>
              )}
            </div>
            <div
              ref={terminalRef}
              className="p-4 font-mono text-sm space-y-1 max-h-96 overflow-y-auto"
            >
              {streamLines.map((line, i) => (
                <StreamLineView key={i} line={line} />
              ))}
              {streaming && (
                <div className="flex items-center gap-2 text-slate-500 text-xs">
                  <span className="animate-pulse">▋</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Posts */}
        {plan.posts.length > 0 && (
          <div className="space-y-4">
            {plan.posts.map(post => (
              <PostCard key={post.id} post={post} wsId={wsId!} onUpdate={updatePost} onDelete={deletePost} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

function StreamLineView({ line }: { line: StreamLine }) {
  switch (line.type) {
    case 'status':
      return <p className="text-slate-400">← {line.message}</p>

    case 'strategy_done':
      return (
        <div>
          <p className="text-green-400">✓ اكتملت الاستراتيجية — {line.ideas?.length} أفكار</p>
          {line.ideas?.map(idea => (
            <p key={idea.day} className="text-slate-500 text-xs mr-4">
              اليوم {idea.day}: {idea.theme} <span className="text-slate-600">({idea.format})</span>
            </p>
          ))}
        </div>
      )

    case 'post_start':
      return <p className="text-yellow-400">✍ {line.message}</p>

    case 'post_written':
      return (
        <div className="mr-4">
          <p className="text-slate-300 text-xs leading-relaxed whitespace-pre-wrap line-clamp-3">{line.content}</p>
          {(line.hashtags ?? []).length > 0 && (
            <p className="text-indigo-400 text-xs mt-0.5">{(line.hashtags ?? []).join(' ')}</p>
          )}
        </div>
      )

    case 'critic_start':
      return <p className="text-slate-500 text-xs mr-2">🔍 {line.message}</p>

    case 'critic_revision':
      return (
        <div>
          <p className="text-orange-400 text-xs">⚠ {line.message}</p>
          {(line.issues ?? []).map((issue, i) => (
            <p key={i} className="text-slate-500 text-xs mr-4">· {issue}</p>
          ))}
        </div>
      )

    case 'post_approved':
      return <p className="text-green-400">✓ {line.message}</p>

    case 'done':
      return <p className="text-green-300 font-semibold">🎉 تم توليد جميع المنشورات وحفظها!</p>

    case 'error':
      return <p className="text-red-400">✗ خطأ: {line.message}</p>

    default:
      return null
  }
}
