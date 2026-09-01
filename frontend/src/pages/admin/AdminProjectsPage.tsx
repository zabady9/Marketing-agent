import {
  listAdminProjects,
  restoreAdminProject,
  softDeleteAdminProject,
  updateAdminProject,
} from '../../adminApi'
import type { ProjectAdminResponse } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { ProjectForm } from './forms/ProjectForm'

// No create endpoint for Project — every project needs a BusinessProfile,
// created only via the existing wizard flow — so `create` is intentionally
// omitted from this config (no "+ New" button rendered).
const config: AdminEntityConfig<ProjectAdminResponse> = {
  title: 'Projects',
  idKey: 'id',
  columns: [
    { header: 'Name', render: (row) => <span className="font-medium text-gray-900">{row.name}</span> },
    { header: 'Status', render: (row) => row.status },
    { header: 'Studies', render: (row) => row.active_study_count },
    { header: 'Chat Sessions', render: (row) => row.active_chat_session_count },
    { header: 'Created', render: (row) => new Date(row.created_at).toLocaleString() },
  ],
  list: listAdminProjects,
  update: (id, payload) => updateAdminProject(id, payload),
  softDelete: softDeleteAdminProject,
  restore: restoreAdminProject,
  cascadeWarning: (row) =>
    `Also soft-deletes ${row.active_study_count} stud${row.active_study_count === 1 ? 'y' : 'ies'} and ${row.active_chat_session_count} chat session${row.active_chat_session_count === 1 ? '' : 's'}.`,
  renderForm: (props) => <ProjectForm {...props} />,
}

export function AdminProjectsPage() {
  return <AdminEntityPage config={config} />
}
