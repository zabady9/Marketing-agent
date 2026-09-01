import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { BusinessProfilePage } from './pages/BusinessProfilePage'
import { ChatPage } from './pages/ChatPage'
import { ChatRedirect } from './pages/ChatRedirect'
import { MemoryPage } from './pages/MemoryPage'
import { ProjectsListPage } from './pages/ProjectsListPage'
import { QuestionnairePage } from './pages/QuestionnairePage'
import { StudyReportPage } from './pages/StudyReportPage'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AdminLayout } from './pages/admin/AdminLayout'
import { AdminProjectsPage } from './pages/admin/AdminProjectsPage'
import { AdminStudyResultsPage } from './pages/admin/AdminStudyResultsPage'
import { AdminChatSessionsPage } from './pages/admin/AdminChatSessionsPage'
import { AdminChatMessagesPage } from './pages/admin/AdminChatMessagesPage'
import { AdminMemoryEntriesPage } from './pages/admin/AdminMemoryEntriesPage'
import { AdminGlossaryCachePage } from './pages/admin/AdminGlossaryCachePage'

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ProjectsListPage />} />
          <Route path="/projects/new" element={<QuestionnairePage />} />
          <Route path="/projects/:projectId" element={<BusinessProfilePage />} />
          <Route path="/projects/:projectId/chat" element={<ChatRedirect />} />
          <Route path="/projects/:projectId/chat/:sessionId" element={<ChatPage />} />
          <Route path="/projects/:projectId/studies/:studyId" element={<StudyReportPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="projects" replace />} />
            <Route path="projects" element={<AdminProjectsPage />} />
            <Route path="studies" element={<AdminStudyResultsPage />} />
            <Route path="chat-sessions" element={<AdminChatSessionsPage />} />
            <Route path="chat-sessions/:sessionId/messages" element={<AdminChatMessagesPage />} />
            <Route path="memory" element={<AdminMemoryEntriesPage />} />
            <Route path="glossary" element={<AdminGlossaryCachePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
