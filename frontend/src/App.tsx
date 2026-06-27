import { Routes, Route, Navigate } from 'react-router-dom'
import WorkspacesPage from './pages/WorkspacesPage'
import WorkspacePage from './pages/WorkspacePage'
import PlanPage from './pages/PlanPage'
import AdminLayout from './pages/admin/AdminLayout'
import AdminDashboardPage from './pages/admin/AdminDashboardPage'
import AdminWorkspacesPage from './pages/admin/AdminWorkspacesPage'
import AdminPlansPage from './pages/admin/AdminPlansPage'
import AdminPostsPage from './pages/admin/AdminPostsPage'
import AdminLogsPage from './pages/admin/AdminLogsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WorkspacesPage />} />
      <Route path="/workspaces/:wsId" element={<WorkspacePage />} />
      <Route path="/workspaces/:wsId/plans/:planId" element={<PlanPage />} />

      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<AdminDashboardPage />} />
        <Route path="workspaces" element={<AdminWorkspacesPage />} />
        <Route path="plans" element={<AdminPlansPage />} />
        <Route path="posts" element={<AdminPostsPage />} />
        <Route path="logs" element={<AdminLogsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
