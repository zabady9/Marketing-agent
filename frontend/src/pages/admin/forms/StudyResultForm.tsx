import { useState, type FormEvent } from 'react'
import type { StudyResultAdminResponse } from '../../../adminTypes'
import type { AdminFormProps } from '../AdminEntityPage'

function stringifyJsonField(value: unknown): string {
  if (value === null || value === undefined) return ''
  return JSON.stringify(value, null, 2)
}

// Parses a JSON textarea's raw text into a plain object, or returns an error
// message. An empty textarea is treated as "unset" (null), not an error.
function parseJsonObjectField(raw: string, fieldLabel: string): { value: Record<string, unknown> | null; error: string | null } {
  const trimmed = raw.trim()
  if (trimmed === '') return { value: null, error: null }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch (err) {
    return { value: null, error: `${fieldLabel}: invalid JSON — ${err instanceof Error ? err.message : String(err)}` }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { value: null, error: `${fieldLabel} must be a JSON object (e.g. {"key": "value"}).` }
  }
  return { value: parsed as Record<string, unknown>, error: null }
}

export function StudyResultForm({ mode, initial, onSubmit, onCancel }: AdminFormProps<StudyResultAdminResponse>) {
  const [projectId, setProjectId] = useState(initial?.project_id ?? '')
  const [status, setStatus] = useState<string>(initial?.status ?? 'pending')
  const [title, setTitle] = useState<string>(initial?.title ?? '')
  const [goal, setGoal] = useState<string>(initial?.goal ?? '')
  const [errorField, setErrorField] = useState(initial?.error ?? '')
  const [startedAt, setStartedAt] = useState(initial?.started_at ?? '')
  const [completedAt, setCompletedAt] = useState(initial?.completed_at ?? '')
  const [reportText, setReportText] = useState(stringifyJsonField(initial?.report ?? {}))

  const [jsonError, setJsonError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setJsonError(null)
    setError(null)

    const reportResult = parseJsonObjectField(reportText, 'Report')
    if (reportResult.error) {
      setJsonError(reportResult.error)
      return
    }

    const payload: Record<string, unknown> = {
      status,
      title: title.trim() === '' ? null : title,
      goal: goal.trim() === '' ? null : goal,
      error: errorField.trim() === '' ? null : errorField,
      started_at: startedAt.trim() === '' ? null : startedAt,
      completed_at: completedAt.trim() === '' ? null : completedAt,
      report: reportResult.value ?? {},
    }
    if (mode === 'create') {
      payload.project_id = projectId
    }

    setIsSubmitting(true)
    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {mode === 'create' && (
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Project ID</label>
          <input
            type="text"
            required
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Status</label>
          <input
            type="text"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
        <div className="col-span-2">
          <label className="mb-1 block text-sm font-medium text-gray-700">Goal</label>
          <input
            type="text"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Started at (ISO)</label>
          <input
            type="text"
            value={startedAt ?? ''}
            onChange={(e) => setStartedAt(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Completed at (ISO)</label>
          <input
            type="text"
            value={completedAt ?? ''}
            onChange={(e) => setCompletedAt(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Error</label>
        <textarea
          value={errorField ?? ''}
          onChange={(e) => setErrorField(e.target.value)}
          rows={2}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Report (raw JSON)</label>
        <textarea
          value={reportText}
          onChange={(e) => setReportText(e.target.value)}
          rows={12}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
        />
      </div>

      {jsonError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{jsonError}</div>
      )}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSubmitting}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {isSubmitting ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}
