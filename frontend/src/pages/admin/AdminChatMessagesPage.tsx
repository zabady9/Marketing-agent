import { Link, useParams } from 'react-router-dom'
import {
  listAdminChatMessages,
  restoreAdminChatMessage,
  softDeleteAdminChatMessage,
  updateAdminChatMessage,
} from '../../adminApi'
import type { ChatMessageAdminResponse, ChatMessageAdminUpdate } from '../../adminTypes'
import { AdminEntityPage, type AdminEntityConfig } from './AdminEntityPage'
import { ChatMessageForm } from './forms/ChatMessageForm'

// Reached only via "View messages" on the chat-sessions list, not a
// standalone top-level nav item — sessionId comes from the route and is a
// fixed, non-user-editable filter (not a free-text field in the toolbar).
export function AdminChatMessagesPage() {
  const { sessionId } = useParams<{ sessionId: string }>()

  const config: AdminEntityConfig<ChatMessageAdminResponse> = {
    title: 'Chat Messages',
    idKey: 'id',
    columns: [
      { header: 'ID', render: (row) => <span className="font-mono text-xs">{row.id}</span> },
      { header: 'Role', render: (row) => row.role },
      {
        header: 'Content',
        render: (row) => <span className="line-clamp-3 max-w-md whitespace-pre-wrap">{row.content}</span>,
      },
      { header: 'Tool', render: (row) => row.tool_name ?? '—' },
      { header: 'Study ID', render: (row) => (row.study_id ? <span className="font-mono text-xs">{row.study_id}</span> : '—') },
      { header: 'Created', render: (row) => new Date(row.created_at).toLocaleString() },
    ],
    list: listAdminChatMessages,
    update: (id, payload) => updateAdminChatMessage(id, payload as ChatMessageAdminUpdate),
    softDelete: softDeleteAdminChatMessage,
    restore: restoreAdminChatMessage,
    filters: { session_id: sessionId },
    headerExtra: (
      <Link to="/admin/chat-sessions" className="mb-1 block text-sm text-gray-500 hover:text-gray-700">
        ← Back to chat sessions
      </Link>
    ),
    renderForm: (props) => <ChatMessageForm {...props} />,
  }

  return <AdminEntityPage config={config} />
}
