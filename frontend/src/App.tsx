import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { Loading } from './components/ui'
import AppShell from './layout/AppShell'
import { Login, Signup } from './pages/Auth'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import Board, { IssueRedirect } from './pages/Board'
import Backlog from './pages/Backlog'
import ProjectSettings from './pages/ProjectSettings'
import Team from './pages/Team'
import Webhooks from './pages/Webhooks'
import Audit from './pages/Audit'
import Billing, { MockCheckout } from './pages/Billing'
import Reports from './pages/Reports'
import MyIssues from './pages/MyIssues'
import Projects from './pages/Projects'

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/signup" element={<Navigate to="/" replace />} />
      <Route path="/" element={<Home />} />
      <Route path="/w/:slug" element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:projectId" element={<Board />} />
        <Route path="projects/:projectId/backlog" element={<Backlog />} />
        <Route path="projects/:projectId/settings" element={<ProjectSettings />} />
        <Route path="issues/:issueId" element={<IssueRedirect />} />
        <Route path="my-issues" element={<MyIssues />} />
        <Route path="team" element={<Team />} />
        <Route path="webhooks" element={<Webhooks />} />
        <Route path="audit" element={<Audit />} />
        <Route path="reports" element={<Reports />} />
        <Route path="billing" element={<Billing />} />
        <Route path="billing/mock-checkout" element={<MockCheckout />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
