import { Routes, Route, Navigate } from 'react-router-dom'
import WorkspacesPage from './pages/WorkspacesPage'
import WorkspacePage from './pages/WorkspacePage'
import SetupWizard from './pages/SetupWizard'
import SubjectProfilePage from './pages/SubjectProfilePage'
import ReportsPage from './pages/ReportsPage'
import ReportDetailPage from './pages/ReportDetailPage'
import ChatPage from './pages/ChatPage'
import AdminLayout from './pages/admin/AdminLayout'
import AdminDashboardPage from './pages/admin/AdminDashboardPage'
import AdminWorkspacesPage from './pages/admin/AdminWorkspacesPage'
import AdminLogsPage from './pages/admin/AdminLogsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WorkspacesPage />} />
      <Route path="/workspaces/:wsId" element={<WorkspacePage />} />
      <Route path="/workspaces/:wsId/setup" element={<SetupWizard />} />
      <Route path="/workspaces/:wsId/subject" element={<SubjectProfilePage />} />
      <Route path="/workspaces/:wsId/reports" element={<ReportsPage />} />
      <Route path="/workspaces/:wsId/reports/:reportId" element={<ReportDetailPage />} />
      <Route path="/workspaces/:wsId/chat" element={<ChatPage />} />
      <Route path="/workspaces/:wsId/chat/:sessionId" element={<ChatPage />} />

      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<AdminDashboardPage />} />
        <Route path="workspaces" element={<AdminWorkspacesPage />} />
        <Route path="logs" element={<AdminLogsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
