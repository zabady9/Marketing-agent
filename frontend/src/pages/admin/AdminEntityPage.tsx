import { useState } from 'react'
import type { ReactNode } from 'react'
import type { AdminListParams, PagedResult } from '../../adminTypes'
import { useAdminList } from '../../hooks/useAdminList'
import { DataTable, type DataTableColumn } from '../../components/report/DataTable'
import { Modal } from '../../components/admin/Modal'
import { ConfirmDialog } from '../../components/admin/ConfirmDialog'
import { Pagination } from '../../components/admin/Pagination'

export interface AdminFormProps<T> {
  mode: 'create' | 'edit'
  initial?: T
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
  onCancel: () => void
}

// Config-driven engine for one entity's admin CRUD page. Every AdminXPage.tsx
// is just ~20 lines building one of these and rendering <AdminEntityPage/>.
export interface AdminEntityConfig<T extends { deleted_at: string | null }> {
  title: string
  idKey: keyof T
  columns: DataTableColumn<T>[]
  list: (params: AdminListParams) => Promise<PagedResult<T>>
  create?: (payload: Record<string, unknown>) => Promise<T>
  update: (id: string, payload: Record<string, unknown>) => Promise<T>
  softDelete: (id: string) => Promise<T>
  restore: (id: string) => Promise<T>
  renderForm: (props: AdminFormProps<T>) => ReactNode
  cascadeWarning?: (row: T) => string | null
  // Fixed, non-user-editable filters (e.g. AdminChatMessagesPage's session_id).
  filters?: Record<string, string | undefined>
  // Extra content rendered next to the title — e.g. a "back to session" link.
  headerExtra?: ReactNode
}

export function AdminEntityPage<T extends { deleted_at: string | null }>({
  config,
}: {
  config: AdminEntityConfig<T>
}) {
  const {
    items,
    setItems,
    state,
    error,
    page,
    totalPages,
    setPage,
    includeDeleted,
    setIncludeDeleted,
    refetch,
  } = useAdminList<T>(config.list, (config.filters ?? {}) as Record<string, string | undefined>)

  const [modal, setModal] = useState<{ mode: 'create' | 'edit'; row?: T } | null>(null)
  const [confirmRow, setConfirmRow] = useState<T | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  function rowId(row: T): string {
    return String(row[config.idKey])
  }

  async function handleFormSubmit(payload: Record<string, unknown>) {
    if (modal?.mode === 'edit' && modal.row) {
      const updated = await config.update(rowId(modal.row), payload)
      setItems((prev) => prev.map((row) => (rowId(row) === rowId(updated) ? updated : row)))
    } else if (config.create) {
      await config.create(payload)
      refetch()
    }
    setModal(null)
  }

  async function handleConfirmDelete() {
    if (!confirmRow) return
    await config.softDelete(rowId(confirmRow))
    setConfirmRow(null)
    refetch()
  }

  // Restore skips the confirm dialog (it's reversible) and updates the row
  // in place instead of a full refetch — same "update local state on
  // success" pattern as MemoryPage's delete handler.
  async function handleRestore(row: T) {
    setActionError(null)
    try {
      const restored = await config.restore(rowId(row))
      setItems((prev) => prev.map((r) => (rowId(r) === rowId(restored) ? restored : r)))
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Restore failed.')
    }
  }

  const columns: DataTableColumn<T>[] = [
    ...config.columns,
    {
      header: 'Status',
      render: (row) =>
        row.deleted_at ? (
          <span className="inline-block rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600 whitespace-nowrap">
            Deleted {new Date(row.deleted_at).toLocaleDateString()}
          </span>
        ) : (
          <span className="inline-block rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
            Active
          </span>
        ),
    },
    {
      header: 'Actions',
      render: (row) =>
        row.deleted_at ? (
          <button
            onClick={() => handleRestore(row)}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            Restore
          </button>
        ) : (
          <div className="flex gap-3">
            <button
              onClick={() => setModal({ mode: 'edit', row })}
              className="text-xs font-medium text-gray-600 hover:text-gray-900 transition-colors"
            >
              Edit
            </button>
            <button
              onClick={() => setConfirmRow(row)}
              className="text-xs font-medium text-red-600 hover:text-red-800 transition-colors"
            >
              Delete
            </button>
          </div>
        ),
    },
  ]

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          {config.headerExtra}
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">{config.title}</h1>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={includeDeleted}
              onChange={(e) => setIncludeDeleted(e.target.checked)}
              className="rounded border-gray-300"
            />
            Include deleted
          </label>
          {config.create && (
            <button
              onClick={() => setModal({ mode: 'create' })}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
            >
              + New
            </button>
          )}
        </div>
      </div>

      {actionError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {state === 'loading' && <p className="text-sm text-gray-500">Loading…</p>}

      {state === 'error' && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error} — is the backend running?
        </div>
      )}

      {state === 'loaded' && items.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500">
          No records found.
        </div>
      )}

      {state === 'loaded' && items.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <DataTable
            columns={columns}
            rows={items}
            rowKey={rowId}
            rowClassName={(row) => (row.deleted_at ? 'opacity-50' : '')}
          />
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === 'create' ? `New ${config.title.replace(/s$/, '')}` : `Edit ${config.title.replace(/s$/, '')}`}
          onClose={() => setModal(null)}
        >
          {config.renderForm({
            mode: modal.mode,
            initial: modal.row,
            onSubmit: handleFormSubmit,
            onCancel: () => setModal(null),
          })}
        </Modal>
      )}

      {confirmRow && (
        <ConfirmDialog
          title={`Delete this ${config.title.replace(/s$/, '').toLowerCase()}?`}
          message={config.cascadeWarning?.(confirmRow) ?? 'This can be restored later from the "Include deleted" view.'}
          confirmLabel="Delete"
          destructive
          onConfirm={handleConfirmDelete}
          onCancel={() => setConfirmRow(null)}
        />
      )}
    </div>
  )
}
