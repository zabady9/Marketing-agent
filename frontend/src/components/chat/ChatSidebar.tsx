import { useState } from 'react'
import { Link } from 'react-router-dom'
import { saveChatArtifact } from '../../api'
import { formatDate, getStudyTitle } from '../../lib/format'
import { FORMAT_ICON, FORMAT_LABEL, formatSize } from '../report/ArtifactCard'
import type { ArtifactListItem, ChatSessionRecord, StudyResultResponse } from '../../types'

// Recent chats shown before "Show all", so Previous studies stays visible
// even in a project with many chats.
const CHATS_PREVIEW = 6

const STUDY_STATUS_DOT: Record<string, string> = {
  pending: 'bg-gray-300',
  running: 'bg-amber-400',
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
}

function GeneratedFileRow({ projectId, file }: { projectId: string; file: ArtifactListItem }) {
  const [state, setState] = useState<'idle' | 'downloading' | 'error'>('idle')
  return (
    <li>
      <button
        type="button"
        onClick={() => {
          setState('downloading')
          saveChatArtifact(projectId, file)
            .then(() => setState('idle'))
            .catch(() => setState('error'))
        }}
        disabled={state === 'downloading'}
        className="flex w-full items-start gap-2 rounded-md border border-transparent px-2.5 py-2 text-start text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-60 transition-colors"
        title={`Download ${file.title} (${FORMAT_LABEL[file.format]})`}
      >
        <span className="shrink-0 leading-4" aria-hidden="true">{FORMAT_ICON[file.format]}</span>
        <span className="min-w-0">
          <span dir="auto" className="block truncate">{file.title}</span>
          <span className="block text-[10px] text-gray-400">
            {state === 'downloading'
              ? 'Downloading…'
              : state === 'error'
                ? <span className="text-red-500">Download failed, click to retry</span>
                : `${file.format.toUpperCase()} · ${formatSize(file.size_bytes)} · ${formatDate(file.created_at)}`}
          </span>
        </span>
      </button>
    </li>
  )
}

// ChatGPT/Claude-style left rail: the project's chats, its previous studies
// and the files generated in it, each one click away without leaving the
// chat. On small screens it renders as an off-canvas drawer toggled by the
// parent.
export function ChatSidebar({
  projectId,
  sessionId,
  sessions,
  studies,
  files,
  open,
  onClose,
  onNewChat,
}: {
  projectId?: string
  sessionId?: string
  sessions: ChatSessionRecord[]
  studies: StudyResultResponse[]
  files: ArtifactListItem[]
  open: boolean
  onClose: () => void
  onNewChat: () => void
}) {
  const [showAllChats, setShowAllChats] = useState(false)
  const activeIndex = sessions.findIndex((s) => s.id === sessionId)
  const visibleSessions =
    showAllChats || sessions.length <= CHATS_PREVIEW
      ? sessions
      : sessions.filter((_, i) => i < CHATS_PREVIEW || i === activeIndex)
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-20 bg-black/30 sm:hidden" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 transform border-r border-gray-200 bg-white transition-transform sm:static sm:z-auto sm:w-60 sm:translate-x-0 shrink-0 flex flex-col ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="shrink-0 px-3 pt-4 pb-3">
          <button
            onClick={() => {
              onNewChat()
              onClose()
            }}
            className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
          >
            + New chat
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-4 space-y-5">
          <section>
            <p className="px-2.5 mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              Chats
            </p>
            <ul className="space-y-1">
              {visibleSessions.map((s) => (
                <li key={s.id}>
                  <Link
                    to={`/projects/${projectId}/chat/${s.id}`}
                    onClick={onClose}
                    className={`block rounded-md px-2.5 py-2 text-xs truncate transition-colors ${
                      s.id === sessionId
                        ? 'bg-indigo-50 border border-indigo-300 text-indigo-900'
                        : 'border border-transparent text-gray-600 hover:bg-gray-50'
                    }`}
                    title={s.title ?? 'New chat'}
                  >
                    {s.title ?? 'New chat'}
                  </Link>
                </li>
              ))}
            </ul>
            {sessions.length > CHATS_PREVIEW && (
              <button
                type="button"
                onClick={() => setShowAllChats((v) => !v)}
                className="mt-1 px-2.5 text-[11px] font-medium text-indigo-600 hover:text-indigo-700"
              >
                {showAllChats ? 'Show fewer' : `Show all (${sessions.length})`}
              </button>
            )}
          </section>

          <section>
            <p className="px-2.5 mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              Previous studies
            </p>
            {studies.length === 0 ? (
              <p className="px-2.5 text-xs text-gray-400">No studies yet.</p>
            ) : (
              <ul className="space-y-1">
                {studies.map((study) => {
                  const title = getStudyTitle(study)
                  return (
                    <li key={study.id}>
                      <Link
                        to={`/projects/${projectId}/studies/${study.id}`}
                        onClick={onClose}
                        className="flex items-start gap-2 rounded-md border border-transparent px-2.5 py-2 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
                        title={title}
                      >
                        <span
                          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                            STUDY_STATUS_DOT[study.status] ?? 'bg-gray-300'
                          }`}
                          aria-label={study.status}
                        />
                        <span className="min-w-0">
                          <span dir="auto" className="block truncate">{title}</span>
                          <span className="block text-[10px] text-gray-400">
                            {formatDate(study.completed_at ?? study.started_at ?? study.created_at)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          <section>
            <p className="px-2.5 mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              Generated files
            </p>
            {files.length === 0 || !projectId ? (
              <p className="px-2.5 text-xs text-gray-400">No files yet. Ask for a Word, PowerPoint or PDF.</p>
            ) : (
              <ul className="space-y-1">
                {files.map((file) => (
                  <GeneratedFileRow key={file.id} projectId={projectId} file={file} />
                ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </>
  )
}
