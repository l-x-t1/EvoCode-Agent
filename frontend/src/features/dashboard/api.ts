import { request } from '@/api/client'
import { endpoints } from '@/api/endpoints'
import type {
  DashboardSummary,
  DashboardTrends,
  SkillEvent,
  SystemHealth,
} from '@/types/api'

export const fetchSummary = () => request<DashboardSummary>(endpoints.dashboardSummary)

export const fetchTrends = (range: '7d' | '14d' | '30d') =>
  request<DashboardTrends>(endpoints.dashboardTrends(range))

export const fetchAgentStatus = () =>
  request<{ total: number; items: { name: string; value: number }[] }>(endpoints.agentStatus)

export const fetchSkillEvents = () =>
  request<{ items: SkillEvent[] }>(endpoints.skillEvents(10))

export const fetchSystemHealth = () => request<SystemHealth>(endpoints.systemHealth)
