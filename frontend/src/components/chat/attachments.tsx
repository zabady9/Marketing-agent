import { useCallback, useEffect, useRef, useState } from 'react'
import {
  completeAttachment,
  createAttachment,
  deleteAttachment,
  getAttachment,
  uploadToTarget,
} from '../../api'
import type { AttachmentSummary } from '../../types'

// Mirrors app/config.py::max_upload_bytes — checked here too so an oversize
// file fails instantly instead of after a round trip.
export const MAX_ATTACHMENT_BYTES = 2 * 1024 ** 3
const POLL_INTERVAL_MS = 2000

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB']
  let value = n / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(1)} ${units[i]}`
}

export type PendingPhase = 'uploading' | 'processing' | 'ready' | 'failed' | 'error'

export interface PendingAttachment {
  localId: string
  name: string
  size: number
  phase: PendingPhase
  progress: number
  attachment?: AttachmentSummary
  error?: string
}

// Drives each picked file through create → PUT bytes → complete → poll
// until processed. "failed" means the backend couldn't read the file's
// content (it can still be sent, as metadata only); "error" means the
// upload itself failed and the file can't be sent.
export function usePendingAttachments(projectId?: string, sessionId?: string) {
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const controllers = useRef(new Map<string, AbortController>())

  const update = useCallback((localId: string, patch: Partial<PendingAttachment>) => {
    setPending((prev) => prev.map((p) => (p.localId === localId ? { ...p, ...patch } : p)))
  }, [])

  // Pending uploads belong to one session — drop them when switching.
  useEffect(() => {
    const active = controllers.current
    return () => {
      active.forEach((c) => c.abort())
      active.clear()
      setPending([])
    }
  }, [projectId, sessionId])

  const uploadOne = useCallback(
    async (localId: string, file: File) => {
      if (!projectId || !sessionId) return
      const controller = new AbortController()
      controllers.current.set(localId, controller)
      const { signal } = controller
      try {
        const { attachment, upload } = await createAttachment(projectId, sessionId, file)
        update(localId, { attachment })
        await uploadToTarget(upload, file, (progress) => update(localId, { progress }), signal)
        let current = await completeAttachment(projectId, sessionId, attachment.id)
        update(localId, { phase: 'processing', progress: 1, attachment: current })
        while (current.status === 'processing' || current.status === 'pending_upload') {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
          if (signal.aborted) return
          current = await getAttachment(projectId, sessionId, current.id)
        }
        update(localId, {
          phase: current.status === 'ready' ? 'ready' : 'failed',
          attachment: current,
          error: current.error ?? undefined,
        })
      } catch (err) {
        if (signal.aborted) return
        update(localId, { phase: 'error', error: err instanceof Error ? err.message : 'Upload failed.' })
      } finally {
        controllers.current.delete(localId)
      }
    },
    [projectId, sessionId, update],
  )

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      Array.from(files).forEach((file, i) => {
        const localId = `att-${Date.now()}-${i}-${file.name}`
        const tooBig = file.size > MAX_ATTACHMENT_BYTES
        setPending((prev) => [
          ...prev,
          {
            localId,
            name: file.name,
            size: file.size,
            phase: tooBig ? 'error' : 'uploading',
            progress: 0,
            error: tooBig ? `Larger than the ${formatBytes(MAX_ATTACHMENT_BYTES)} limit.` : undefined,
          },
        ])
        if (!tooBig) uploadOne(localId, file)
      })
    },
    [uploadOne],
  )

  const remove = useCallback(
    (item: PendingAttachment) => {
      controllers.current.get(item.localId)?.abort()
      if (item.attachment && projectId && sessionId) {
        deleteAttachment(projectId, sessionId, item.attachment.id).catch(() => {})
      }
      setPending((prev) => prev.filter((p) => p.localId !== item.localId))
    },
    [projectId, sessionId],
  )

  // After a send: forget the sent chips without deleting them server-side.
  const clearSent = useCallback(() => {
    setPending((prev) => prev.filter((p) => p.phase !== 'ready' && p.phase !== 'failed'))
  }, [])

  const sendable = pending.filter((p) => (p.phase === 'ready' || p.phase === 'failed') && p.attachment)
  const busy = pending.some((p) => p.phase === 'uploading' || p.phase === 'processing')

  return { pending, addFiles, remove, clearSent, sendable, busy }
}

function phaseLabel(p: PendingAttachment): string {
  if (p.phase === 'uploading') return `${Math.round(p.progress * 100)}%`
  if (p.phase === 'processing') return 'Reading…'
  if (p.phase === 'failed') return 'Name only'
  if (p.phase === 'error') return p.error ?? 'Failed'
  return formatBytes(p.size)
}

export function PendingAttachmentChips({
  pending,
  onRemove,
}: {
  pending: PendingAttachment[]
  onRemove: (item: PendingAttachment) => void
}) {
  if (pending.length === 0) return null
  return (
    <div className="max-w-2xl mx-auto mb-2 flex flex-wrap gap-2">
      {pending.map((p) => (
        <div
          key={p.localId}
          title={p.phase === 'failed' ? `Couldn't read this file's content: ${p.error ?? ''}` : p.name}
          className={`relative overflow-hidden flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs ${
            p.phase === 'error'
              ? 'border-red-200 bg-red-50 text-red-700'
              : p.phase === 'failed'
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : 'border-gray-200 bg-gray-50 text-gray-700'
          }`}
        >
          {p.phase === 'uploading' && (
            <div
              className="absolute inset-y-0 left-0 bg-indigo-100 transition-[width]"
              style={{ width: `${p.progress * 100}%` }}
            />
          )}
          <span className="relative">📎</span>
          <span className="relative max-w-[12rem] truncate font-medium">{p.name}</span>
          <span className="relative text-gray-500 max-w-[14rem] truncate">{phaseLabel(p)}</span>
          <button
            type="button"
            onClick={() => onRemove(p)}
            className="relative ml-1 text-gray-400 hover:text-gray-700"
            aria-label={`Remove ${p.name}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}

// Shown inside a sent user bubble (indigo background).
export function SentAttachmentChips({ attachments }: { attachments: AttachmentSummary[] }) {
  if (attachments.length === 0) return null
  return (
    <div className="mb-1.5 flex flex-wrap gap-1.5">
      {attachments.map((a) => (
        <span
          key={a.id}
          title={`${a.filename} (${a.content_type})`}
          className="inline-flex items-center gap-1 rounded bg-indigo-500/60 px-2 py-0.5 text-xs"
        >
          📎 <span className="max-w-[12rem] truncate">{a.filename}</span>
          <span className="opacity-75">{formatBytes(a.size_bytes)}</span>
        </span>
      ))}
    </div>
  )
}
