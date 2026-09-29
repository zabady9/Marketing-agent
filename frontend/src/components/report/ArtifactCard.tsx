import { useState } from 'react'
import { downloadChatArtifact } from '../../api'
import { SectionCardShell } from './primitives'
import type { ArtifactSummary } from '../../types'

const FORMAT_LABEL: Record<ArtifactSummary['format'], string> = {
  docx: 'Word Document',
  pptx: 'PowerPoint',
  pdf: 'PDF',
}

const FORMAT_ICON: Record<ArtifactSummary['format'], string> = {
  docx: '📄',
  pptx: '📊',
  pdf: '📕',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// A safe, human-readable filename for the client-side download — the
// backend independently derives its own from the same title for the rare
// case a file is opened directly via the download URL.
function downloadFilename(artifact: ArtifactSummary): string {
  const slug = artifact.title.replace(/[\\/:*?"<>|]/g, '_').trim() || 'artifact'
  return `${slug}.${artifact.format}`
}

export function ArtifactCard({ projectId, artifact }: { projectId: string; artifact: ArtifactSummary }) {
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDownload() {
    setDownloading(true)
    setError(null)
    try {
      const blob = await downloadChatArtifact(projectId, artifact)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = downloadFilename(artifact)
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to download the file.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <SectionCardShell title={`${FORMAT_ICON[artifact.format]} ${FORMAT_LABEL[artifact.format]}`}>
      <p className="text-sm font-medium text-gray-900">{artifact.title}</p>
      <p className="mt-0.5 text-xs text-gray-500">{formatSize(artifact.size_bytes)}</p>
      <button
        onClick={handleDownload}
        disabled={downloading}
        className="mt-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {downloading ? 'Downloading…' : 'Download'}
      </button>
      {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
    </SectionCardShell>
  )
}
