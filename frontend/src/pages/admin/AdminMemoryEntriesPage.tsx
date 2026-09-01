import {
  listAdminMemoryEntries,
  restoreAdminMemoryEntry,
  softDeleteAdminMemoryEntry,
  updateAdminMemoryEntry,
} from '../../adminApi'
import type { MemoryEntryAdminResponse, MemoryEntryAdminUpdate } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { MemoryEntryForm } from './forms/MemoryEntryForm'

// No create endpoint in the admin API — the existing public POST /api/memory
// already covers it — so `create` is intentionally omitted (no "+ New").
const config: AdminEntityConfig<MemoryEntryAdminResponse> = {
  title: 'Memory Entries',
  idKey: 'id',
  columns: [
    { header: 'Content', render: (row) => <span className="line-clamp-2 max-w-lg">{row.content}</span> },
    { header: 'Source', render: (row) => row.source },
    { header: 'Updated', render: (row) => new Date(row.updated_at).toLocaleString() },
  ],
  list: listAdminMemoryEntries,
  update: (id, payload) => updateAdminMemoryEntry(id, payload as MemoryEntryAdminUpdate),
  softDelete: softDeleteAdminMemoryEntry,
  restore: restoreAdminMemoryEntry,
  renderForm: (props) => <MemoryEntryForm {...props} />,
}

export function AdminMemoryEntriesPage() {
  return <AdminEntityPage config={config} />
}
