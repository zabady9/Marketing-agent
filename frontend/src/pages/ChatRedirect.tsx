import { useEffect, useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { createChatSession, listChatSessions } from '../api'

// Resolves the session-less `/projects/:projectId/chat` link (used by
// BusinessProfilePage) to a concrete session: the most recently updated one,
// or a freshly created one if the project has none yet.
export function ChatRedirect() {
  const { projectId } = useParams<{ projectId: string }>()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    listChatSessions(projectId)
      .then((sessions) => {
        if (cancelled) return
        if (sessions.length > 0) {
          setSessionId(sessions[0].id)
          return
        }
        return createChatSession(projectId).then((session) => {
          if (cancelled) return
          setSessionId(session.id)
        })
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load chat.')
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      </div>
    )
  }

  if (!sessionId || !projectId) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-400">Loading conversation…</p>
      </div>
    )
  }

  return <Navigate to={`/projects/${projectId}/chat/${sessionId}`} replace />
}
