import { useCallback, useEffect, useRef, useState } from 'react'
import { getStudyById, StudyNotFoundError } from '../api'
import type { StudyResultResponse } from '../types'

const POLL_MS = 4000

export type StudyLoadState = 'loading' | 'loaded' | 'not_found' | 'error'

// Loads one analysis and keeps polling while it's pending or running, so the
// report page and chat cards show real progress after a refresh — they never
// depend on having seen the live stream.
export function useStudy(projectId: string | undefined, studyId: string | undefined) {
  const [study, setStudy] = useState<StudyResultResponse | null>(null)
  const [state, setState] = useState<StudyLoadState>('loading')
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)

  const load = useCallback(async () => {
    if (!projectId || !studyId) return
    try {
      const data = await getStudyById(projectId, studyId)
      if (cancelled.current) return
      setStudy(data)
      setState('loaded')
      setError(null)
    } catch (err) {
      if (cancelled.current) return
      if (err instanceof StudyNotFoundError) {
        setState('not_found')
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to load the analysis.')
      // Keep showing the last good data if a poll fails.
      setState((prev) => (prev === 'loaded' ? prev : 'error'))
    }
  }, [projectId, studyId])

  useEffect(() => {
    cancelled.current = false
    setStudy(null)
    setState('loading')
    load()
    return () => {
      cancelled.current = true
    }
  }, [load])

  const inProgress = study?.status === 'pending' || study?.status === 'running'
  useEffect(() => {
    if (!inProgress) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [inProgress, load])

  return { study, state, error, reload: load }
}
