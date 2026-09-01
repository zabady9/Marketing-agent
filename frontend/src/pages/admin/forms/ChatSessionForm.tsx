import { useState, type FormEvent } from 'react'
import type { ChatSessionAdminResponse } from '../../../adminTypes'
import type { AdminFormProps } from '../AdminEntityPage'

// No create endpoint for ChatSession (the public endpoint already covers
// creation) — this form is edit-only in practice.
export function ChatSessionForm({ initial, onSubmit, onCancel }: AdminFormProps<ChatSessionAdminResponse>) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      await onSubmit({ title: title.trim() === '' ? null : title })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Title</label>
        <input
          type="text"
          value={title ?? ''}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="(untitled)"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
        />
      </div>

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
