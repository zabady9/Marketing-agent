import {
  listAdminGlossaryCache,
  restoreAdminGlossaryCache,
  softDeleteAdminGlossaryCache,
  updateAdminGlossaryCache,
} from '../../adminApi'
import type { GlossaryCacheAdminResponse, GlossaryCacheAdminUpdate } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { GlossaryCacheForm } from './forms/GlossaryCacheForm'

// Primary key is `language`, not `id`. No create endpoint — rows are created
// implicitly by the app's translation cache — so `create` is omitted.
const config: AdminEntityConfig<GlossaryCacheAdminResponse> = {
  title: 'Glossary Cache',
  idKey: 'language',
  columns: [
    { header: 'Language', render: (row) => <span className="font-mono text-xs">{row.language}</span> },
    { header: 'Terms', render: (row) => `${Object.keys(row.terms).length} terms` },
    { header: 'Created', render: (row) => new Date(row.created_at).toLocaleString() },
  ],
  list: listAdminGlossaryCache,
  update: (language, payload) => updateAdminGlossaryCache(language, payload as unknown as GlossaryCacheAdminUpdate),
  softDelete: softDeleteAdminGlossaryCache,
  restore: restoreAdminGlossaryCache,
  renderForm: (props) => <GlossaryCacheForm {...props} />,
}

export function AdminGlossaryCachePage() {
  return <AdminEntityPage config={config} />
}
