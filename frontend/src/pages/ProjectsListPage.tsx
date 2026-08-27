import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listProjects } from '../api'
import type { ProjectSummary } from '../types'

type LoadState = 'loading' | 'loaded' | 'error'

export function ProjectsListPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listProjects()
      .then((data) => {
        if (cancelled) return
        setProjects(data)
        setState('loaded')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load projects.')
        setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">Projects</h1>
          <Link
            to="/projects/new"
            className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
          >
            + New Project
          </Link>
        </div>

        {state === 'loading' && <p className="text-gray-500 text-sm">Loading projects…</p>}

        {state === 'error' && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error} — is the backend running?
          </div>
        )}

        {state === 'loaded' && projects.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-16 text-center">
            <p className="text-gray-500 mb-4">No projects yet.</p>
            <Link
              to="/projects/new"
              className="inline-block rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
            >
              Create your first project
            </Link>
          </div>
        )}

        {state === 'loaded' && projects.length > 0 && (
          <ul className="space-y-3">
            {projects.map((project) => (
              <li key={project.id}>
                <Link
                  to={`/projects/${project.id}`}
                  className="block rounded-lg border border-gray-200 bg-white px-5 py-4 hover:border-indigo-300 hover:shadow-sm transition-all"
                >
                  <p className="font-medium text-gray-900 truncate" title={project.name}>
                    {project.name}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    {new Date(project.created_at).toLocaleString()} · {project.status}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
