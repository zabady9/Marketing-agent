import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { BusinessProfilePage } from './pages/BusinessProfilePage'
import { ChatPage } from './pages/ChatPage'
import { ChatRedirect } from './pages/ChatRedirect'
import { MemoryPage } from './pages/MemoryPage'
import { ProjectsListPage } from './pages/ProjectsListPage'
import { QuestionnairePage } from './pages/QuestionnairePage'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectsListPage />} />
        <Route path="/projects/new" element={<QuestionnairePage />} />
        <Route path="/projects/:projectId" element={<BusinessProfilePage />} />
        <Route path="/projects/:projectId/chat" element={<ChatRedirect />} />
        <Route path="/projects/:projectId/chat/:sessionId" element={<ChatPage />} />
        <Route path="/memory" element={<MemoryPage />} />
      </Routes>
    </BrowserRouter>
  )
}
