import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'

// Minimal modal primitive — this codebase has no dialog component anywhere
// else, so this is built from scratch rather than pulling in a dependency.
// Closes on overlay click and Escape; portaled to document.body so it isn't
// clipped by an ancestor's overflow/stacking context.
export function Modal({
  title,
  onClose,
  children,
  widthClassName = 'max-w-lg',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  widthClassName?: string
}) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-8"
      onClick={onClose}
    >
      <div
        className={`w-full ${widthClassName} max-h-full overflow-y-auto rounded-xl bg-white shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
