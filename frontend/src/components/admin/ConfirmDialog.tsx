import type { ReactNode } from 'react'
import { useState } from 'react'
import { Modal } from './Modal'

// Used for every soft-delete confirmation across the admin panel. Restore
// actions deliberately skip this — restore is reversible, delete isn't.
export function ConfirmDialog({
  title,
  message,
  children,
  confirmLabel = 'Confirm',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  title: string
  message?: string
  children?: ReactNode
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => Promise<void> | void
  onCancel: () => void
}) {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setIsSubmitting(true)
    setError(null)
    try {
      await onConfirm()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.')
      setIsSubmitting(false)
    }
  }

  return (
    <Modal title={title} onClose={onCancel} widthClassName="max-w-md">
      <div className="space-y-4">
        {message && <p className="text-sm text-gray-600">{message}</p>}
        {children}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onCancel}
            disabled={isSubmitting}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={isSubmitting}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 transition-colors ${
              destructive ? 'bg-red-600 hover:bg-red-700' : 'bg-indigo-600 hover:bg-indigo-700'
            }`}
          >
            {isSubmitting ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
