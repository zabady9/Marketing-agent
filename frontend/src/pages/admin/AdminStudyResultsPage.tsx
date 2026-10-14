import {
  createAdminStudy,
  listAdminStudies,
  restoreAdminStudy,
  softDeleteAdminStudy,
  updateAdminStudy,
} from '../../adminApi'
import type { StudyResultAdminCreate, StudyResultAdminResponse, StudyResultAdminUpdate } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { StudyResultForm } from './forms/StudyResultForm'

const config: AdminEntityConfig<StudyResultAdminResponse> = {
  title: 'Studies',
  idKey: 'id',
  columns: [
    { header: 'ID', render: (row) => <span className="font-mono text-xs">{row.id}</span> },
    { header: 'Project ID', render: (row) => <span className="font-mono text-xs">{row.project_id}</span> },
    { header: 'Title', render: (row) => row.title ?? '—' },
    { header: 'Status', render: (row) => row.status },
    { header: 'Steps', render: (row) => row.report?.steps?.length ?? 0 },
    { header: 'Created', render: (row) => new Date(row.created_at).toLocaleString() },
  ],
  list: listAdminStudies,
  create: (payload) => createAdminStudy(payload as unknown as StudyResultAdminCreate),
  update: (id, payload) => updateAdminStudy(id, payload as StudyResultAdminUpdate),
  softDelete: softDeleteAdminStudy,
  restore: restoreAdminStudy,
  renderForm: (props) => <StudyResultForm {...props} />,
}

export function AdminStudyResultsPage() {
  return <AdminEntityPage config={config} />
}
