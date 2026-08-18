import type { StartStudyRequest } from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8007'

export async function startStudy(payload: StartStudyRequest): Promise<string> {
  const res = await fetch(`${BASE}/api/feasibility/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`HTTP ${res.status}: ${body}`)
  }
  const data = (await res.json()) as { study_id: string }
  return data.study_id
}

export function openStream(studyId: string): EventSource {
  return new EventSource(`${BASE}/api/feasibility/${studyId}/stream`)
}
