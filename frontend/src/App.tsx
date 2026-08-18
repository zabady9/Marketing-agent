import { useState, useCallback, useRef } from 'react'
import { InputForm } from './components/InputForm'
import { startStudy, openStream } from './api'
import type { StartStudyRequest } from './types'

type AppView = 'form' | 'study'

export function App() {
  const [view, setView] = useState<AppView>('form')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [studyId, setStudyId] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const handleSubmit = useCallback(async (payload: StartStudyRequest) => {
    setIsSubmitting(true)
    try {
      const id = await startStudy(payload)
      setStudyId(id)

      // Open SSE stream
      const es = openStream(id)
      esRef.current = es

      es.onopen = () => {
        console.info('[SSE] stream opened for study', id)
      }

      // Route named events to console (Phase 7a: log only; rendering wired in Phase 7b)
      const LOG_EVENTS = [
        'study_started', 'language_detected', 'intake_warning', 'intake_error',
        'agent_started', 'agent_completed', 'agent_failed', 'agent_warning',
        'search_query_sent', 'search_results_received',
        'calc_started', 'calc_completed', 'calc_failed',
        'section_ready',
        'qc_started', 'qc_flag_raised', 'qc_completed',
        'study_completed', 'study_failed',
      ]

      for (const eventType of LOG_EVENTS) {
        es.addEventListener(eventType, (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data)
            console.info(`[SSE] ${eventType}`, data)
          } catch {
            console.warn(`[SSE] ${eventType} — failed to parse:`, e.data)
          }
        })
      }

      es.onerror = (e) => {
        console.error('[SSE] connection error', e)
      }

      setView('study')
    } finally {
      setIsSubmitting(false)
    }
  }, [])

  if (view === 'form') {
    return <InputForm onSubmit={handleSubmit} isSubmitting={isSubmitting} />
  }

  // Phase 7a placeholder — full progress + report in Phase 7b/7c
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4">
      <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      <p className="text-sm text-gray-500">
        Study <span className="font-mono text-gray-700">{studyId}</span> is running.
      </p>
      <p className="text-xs text-gray-400">
        Open browser DevTools → Network → EventSource to see live events.
      </p>
    </div>
  )
}
