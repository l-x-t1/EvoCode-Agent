import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy } from 'react'
import { AppShell } from '@/app/layouts/AppShell'
import { RouteError } from '@/app/RouteError'

// 路由级分包（docs/02 §6）：每个页面独立 chunk
const DashboardPage = lazy(() => import('@/features/dashboard/DashboardPage'))
const WorkspacePage = lazy(() => import('@/features/workspace/WorkspacePage'))
const SkillCenterPage = lazy(() => import('@/features/skills/SkillCenterPage'))
const ContextCenterPage = lazy(() => import('@/features/context/ContextCenterPage'))
const WorkflowPage = lazy(() => import('@/features/workflow/WorkflowPage'))
const EvaluationPage = lazy(() => import('@/features/evaluation/EvaluationPage'))
const SettingsPage = lazy(() => import('@/features/settings/SettingsPage'))
const NotFoundPage = lazy(() => import('@/features/NotFoundPage'))

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'workspace', element: <WorkspacePage /> },
      { path: 'workspace/:taskId', element: <WorkspacePage /> },
      { path: 'skills', element: <SkillCenterPage /> },
      { path: 'skills/:skillId', element: <SkillCenterPage /> },
      { path: 'context', element: <ContextCenterPage /> },
      { path: 'context/:sessionId', element: <ContextCenterPage /> },
      { path: 'workflow', element: <WorkflowPage /> },
      { path: 'workflow/:runId', element: <WorkflowPage /> },
      { path: 'evaluation', element: <EvaluationPage /> },
      { path: 'settings', element: <Navigate to="/settings/models" replace /> },
      { path: 'settings/:section', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
