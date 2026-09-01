import { Link } from 'react-router-dom'
import {
  listAdminChatSessions,
  restoreAdminChatSession,
  softDeleteAdminChatSession,
  updateAdminChatSession,
} from '../../adminApi'
import type { ChatSessionAdminResponse, ChatSessionAdminUpdate } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { ChatSessionForm } from './forms/ChatSessionForm'

// No create endpoint for ChatSession — the public endpoint already covers
// creation — so `create` is intentionally omitted (no "+ New" button).
const config: AdminEntityConfig<ChatSessionAdminResponse> = {
  title: 'Chat Sessions',
  idKey: 'id',
  columns: [
    { header: 'ID', render: (row) => <span className="font-mono text-xs">{row.id}</span> },
    { header: 'Project ID', render: (row) => <span className="font-mono text-xs">{row.project_id}</span> },
    { header: 'Title', render: (row) => row.title ?? <span className="text-gray-400">(untitled)</span> },
    { header: 'Updated', render: (row) => new Date(row.updated_at).toLocaleString() },
    {
      header: 'Messages',
      render: (row) => (
        <Link
          to={`/admin/chat-sessions/${row.id}/messages`}
          className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
        >
          View messages
        </Link>
      ),
    },
  ],
  list: listAdminChatSessions,
  update: (id, payload) => updateAdminChatSession(id, payload as ChatSessionAdminUpdate),
  softDelete: softDeleteAdminChatSession,
  restore: restoreAdminChatSession,
  cascadeWarning: () => 'Also soft-deletes this session\'s chat messages.',
  renderForm: (props) => <ChatSessionForm {...props} />,
}

export function AdminChatSessionsPage() {
  return <AdminEntityPage config={config} />
}
