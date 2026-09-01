import { useState, type FormEvent } from 'react'
import { GLOSSARY_TERM_KEYS, type GlossaryCacheAdminResponse } from '../../../adminTypes'
import type { AdminFormProps } from '../AdminEntityPage'

// terms is a fixed set of 17 known keys — a structured form (one labeled
// input per key) rather than a raw JSON textarea, since the key set is small
// and fixed (see app/services/glossary.py::GLOSSARY_TERMS).
export function GlossaryCacheForm({ initial, onSubmit, onCancel }: AdminFormProps<GlossaryCacheAdminResponse>) {
  const [terms, setTerms] = useState<Record<string, string>>(() => {
    const initialTerms = initial?.terms ?? {}
    const result: Record<string, string> = {}
    for (const key of GLOSSARY_TERM_KEYS) {
      result[key] = initialTerms[key] ?? ''
    }
    return result
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      await onSubmit({ terms })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {initial && (
        <p className="text-xs text-gray-500">
          Language: <span className="font-mono">{initial.language}</span>
        </p>
      )}
      <div className="max-h-96 space-y-3 overflow-y-auto pr-1">
        {GLOSSARY_TERM_KEYS.map((key) => (
          <div key={key}>
            <label className="mb-1 block text-sm font-medium text-gray-700">{key}</label>
            <textarea
              value={terms[key]}
              onChange={(e) => setTerms((prev) => ({ ...prev, [key]: e.target.value }))}
              rows={2}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
            />
          </div>
        ))}
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
