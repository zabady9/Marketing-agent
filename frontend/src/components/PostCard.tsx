import { useState } from 'react'
import { approvePost, rejectPost, editPost, regeneratePost } from '../api'
import type { Post } from '../types'
import ScheduleModal from './ScheduleModal'

interface Props {
  post: Post
  wsId: string
  onUpdate: (updated: Post) => void
}

const STATUS_STYLES: Record<string, string> = {
  pending_approval: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  approved: 'bg-green-100 text-green-700 border-green-200',
  scheduled: 'bg-blue-100 text-blue-700 border-blue-200',
  published: 'bg-purple-100 text-purple-700 border-purple-200',
  rejected: 'bg-red-100 text-red-700 border-red-200',
  draft: 'bg-gray-100 text-gray-600 border-gray-200',
}

const STATUS_LABEL: Record<string, string> = {
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  scheduled: 'Scheduled',
  published: 'Published',
  rejected: 'Rejected',
  draft: 'Draft',
}

const FORMAT_EMOJI: Record<string, string> = {
  thread: '🧵', carousel: '🎠', 'short-video': '🎬', video: '🎬',
  image: '🖼️', reel: '🎬', story: '📱', poll: '📊', quote: '💬',
}

export default function PostCard({ post, wsId, onUpdate }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState(post.content)
  const [editHashtags, setEditHashtags] = useState((post.hashtags || []).join(' '))
  const [editTime, setEditTime] = useState(post.suggested_time)
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [regenNote, setRegenNote] = useState('')
  const [showRegen, setShowRegen] = useState(false)
  const [showSchedule, setShowSchedule] = useState(false)
  const [error, setError] = useState('')

  async function run(label: string, fn: () => Promise<Post | void>) {
    setBusy(label)
    setError('')
    try {
      const result = await fn()
      if (result) onUpdate(result as Post)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(null)
    }
  }

  async function handleSaveEdit() {
    await run('save', async () => {
      const updated = await editPost(post.id, {
        content: editContent,
        hashtags: editHashtags.split(/\s+/).filter(h => h.startsWith('#')).length > 0
          ? editHashtags.split(/\s+/).filter(Boolean)
          : [],
        suggested_time: editTime,
      })
      setEditing(false)
      return updated
    })
  }

  async function handleReject() {
    await run('reject', () => rejectPost(post.id, rejectReason || undefined))
    setShowReject(false)
  }

  async function handleRegen() {
    await run('regen', () => regeneratePost(post.id, regenNote || undefined))
    setShowRegen(false)
  }

  const isTerminal = ['scheduled', 'published', 'rejected'].includes(post.status)

  return (
    <div className={`bg-white border rounded-xl shadow-sm overflow-hidden ${post.status === 'rejected' ? 'opacity-60' : ''}`}>
      {/* Card header */}
      <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-500">Day {post.day}</span>
          <span className="text-gray-300">·</span>
          <span className="text-sm text-gray-600">{FORMAT_EMOJI[post.format] ?? '📝'} {post.format}</span>
          <span className="text-gray-300">·</span>
          <span className="text-sm text-gray-500">{post.suggested_time}</span>
        </div>
        <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${STATUS_STYLES[post.status] ?? STATUS_STYLES.draft}`}>
          {STATUS_LABEL[post.status] ?? post.status}
        </span>
      </div>

      {/* Theme/angle */}
      <div className="px-5 pt-4 pb-2">
        <p className="text-xs font-medium text-indigo-600 uppercase tracking-wide mb-1">{post.theme}</p>
        <p className="text-xs text-gray-400 italic mb-3">{post.angle}</p>

        {/* Content */}
        {editing ? (
          <div className="space-y-3">
            <textarea
              value={editContent}
              onChange={e => setEditContent(e.target.value)}
              rows={5}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            <input
              value={editHashtags}
              onChange={e => setEditHashtags(e.target.value)}
              placeholder="#hashtag1 #hashtag2"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <input
              value={editTime}
              onChange={e => setEditTime(e.target.value)}
              placeholder="09:00"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex gap-2">
              <button onClick={handleSaveEdit} disabled={busy === 'save'} className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors">
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
              <button onClick={() => setEditing(false)} className="px-3 py-1.5 rounded-lg text-xs text-gray-600 hover:bg-gray-100 transition-colors">Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">{post.content}</p>
            {(post.hashtags || []).length > 0 && (
              <p className="text-sm text-indigo-500 mt-2">{post.hashtags.join(' ')}</p>
            )}
          </>
        )}
      </div>

      {/* Error */}
      {error && <p className="px-5 pb-2 text-xs text-red-600">{error}</p>}

      {/* Reject inline form */}
      {showReject && (
        <div className="px-5 pb-4 space-y-2">
          <input
            value={rejectReason}
            onChange={e => setRejectReason(e.target.value)}
            placeholder="Reason (optional)"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
          />
          <div className="flex gap-2">
            <button onClick={handleReject} disabled={busy === 'reject'} className="bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors">
              {busy === 'reject' ? 'Rejecting…' : 'Confirm Reject'}
            </button>
            <button onClick={() => setShowReject(false)} className="px-3 py-1.5 rounded-lg text-xs text-gray-600 hover:bg-gray-100 transition-colors">Cancel</button>
          </div>
        </div>
      )}

      {/* Regen inline form */}
      {showRegen && (
        <div className="px-5 pb-4 space-y-2">
          <input
            value={regenNote}
            onChange={e => setRegenNote(e.target.value)}
            placeholder="Note for AI e.g. make it funnier (optional)"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
          />
          <div className="flex gap-2">
            <button onClick={handleRegen} disabled={busy === 'regen'} className="bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors">
              {busy === 'regen' ? 'Sending…' : 'Regenerate'}
            </button>
            <button onClick={() => setShowRegen(false)} className="px-3 py-1.5 rounded-lg text-xs text-gray-600 hover:bg-gray-100 transition-colors">Cancel</button>
          </div>
        </div>
      )}

      {/* Action bar */}
      {!isTerminal && !editing && !showReject && !showRegen && (
        <div className="px-5 py-3 border-t border-gray-100 bg-gray-50 flex flex-wrap gap-2">
          {post.status === 'pending_approval' && (
            <button
              onClick={() => run('approve', () => approvePost(post.id))}
              disabled={busy !== null}
              className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              {busy === 'approve' ? '…' : '✓ Approve'}
            </button>
          )}
          {post.status === 'approved' && (
            <button
              onClick={() => setShowSchedule(true)}
              className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              📅 Schedule
            </button>
          )}
          <button
            onClick={() => { setEditing(true); setEditContent(post.content); setEditHashtags((post.hashtags || []).join(' ')); setEditTime(post.suggested_time) }}
            className="bg-white border border-gray-300 hover:border-gray-400 text-gray-700 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          >
            ✏️ Edit
          </button>
          <button
            onClick={() => setShowRegen(true)}
            className="bg-white border border-violet-300 hover:border-violet-400 text-violet-700 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          >
            ✨ Regenerate
          </button>
          <button
            onClick={() => setShowReject(true)}
            className="bg-white border border-red-200 hover:border-red-300 text-red-600 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto"
          >
            ✕ Reject
          </button>
        </div>
      )}

      {showSchedule && (
        <ScheduleModal
          post={post}
          wsId={wsId}
          onDone={updated => { onUpdate(updated); setShowSchedule(false) }}
          onClose={() => setShowSchedule(false)}
        />
      )}
    </div>
  )
}
