import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { addMemoryEntry, deleteMemoryEntry, listMemory } from '../api'
import type { MemoryEntry } from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

export function MemoryPage() {
  const [entries, setEntries] = useState<MemoryEntry[]>([])
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState<string | null>(null)
  const [newContent, setNewContent] = useState('')
  const [isAdding, setIsAdding] = useState(false)

  useEffect(() => {
    listMemory()
      .then((data) => {
        setEntries(data)
        setState('loaded')
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load memory.')
        setState('error')
      })
  }, [])

  async function handleAdd() {
    const content = newContent.trim()
    if (!content || isAdding) return
    setIsAdding(true)
    try {
      const entry = await addMemoryEntry(content)
      setEntries((prev) => [entry, ...prev])
      setNewContent('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add memory.')
    } finally {
      setIsAdding(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteMemoryEntry(id)
      setEntries((prev) => prev.filter((e) => e.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete memory.')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <Link to="/" className="text-sm text-gray-500 hover:text-gray-700">
              ← Projects
            </Link>
            <h1 className="text-3xl font-semibold text-gray-900 tracking-tight mt-1">Memory</h1>
            <p className="mt-1 text-sm text-gray-500">
              Facts the assistant remembers across every project's chats.
            </p>
          </div>
        </div>

        <div className="flex gap-2 mb-8">
          <input
            type="text"
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleAdd()
              }
            }}
            placeholder="Add something for the assistant to remember…"
            disabled={isAdding}
            className="flex-1 rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none disabled:opacity-50"
          />
          <button
            onClick={handleAdd}
            disabled={isAdding || !newContent.trim()}
            className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Add
          </button>
        </div>

        {state === 'loading' && <p className="text-gray-500 text-sm">Loading memory…</p>}

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {state === 'loaded' && entries.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-16 text-center">
            <p className="text-gray-500">
              Nothing remembered yet. The assistant will add things it learns, or add one above.
            </p>
          </div>
        )}

        {entries.length > 0 && (
          <ul className="space-y-3">
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="rounded-lg border border-gray-200 bg-white px-5 py-4 flex items-start justify-between gap-4"
              >
                <div className="min-w-0">
                  <p className="text-sm text-gray-900">{entry.content}</p>
                  <p className="mt-1 text-xs text-gray-400">
                    {entry.source === 'agent_extracted' ? 'Learned by assistant' : 'Added by you'} ·{' '}
                    {new Date(entry.created_at).toLocaleString()}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(entry.id)}
                  className="shrink-0 text-xs text-gray-400 hover:text-red-600 transition-colors"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
