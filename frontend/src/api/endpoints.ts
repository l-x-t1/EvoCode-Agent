/**
 * 全部 API 路径常量（与 docs/06 §3 一一对应，含类型标注）。
 * 各 feature 的 api.ts 组合这里的路径与 api/client.request。
 */

export const endpoints = {
  // Dashboard
  dashboardSummary: '/dashboard/summary',
  dashboardTrends: (range: '7d' | '14d' | '30d') => `/dashboard/trends?range=${range}`,
  agentStatus: '/agents/status',
  skillEvents: (limit = 10) => `/skills/events?limit=${limit}`,
  systemHealth: '/system/health',

  // Tasks / Runs
  tasks: (query?: { status?: string; q?: string; page?: number; size?: number }) => {
    const params = new URLSearchParams()
    if (query?.status) params.set('status', query.status)
    if (query?.q) params.set('q', query.q)
    if (query?.page) params.set('page', String(query.page))
    if (query?.size) params.set('size', String(query.size))
    const qs = params.toString()
    return `/tasks${qs ? `?${qs}` : ''}`
  },
  createTask: '/tasks',
  task: (taskId: string) => `/tasks/${taskId}`,
  cancelTask: (taskId: string) => `/tasks/${taskId}/cancel`,
  taskMessages: (taskId: string, cursor?: string) =>
    `/tasks/${taskId}/messages${cursor ? `?cursor=${cursor}` : ''}`,
  taskRuns: (taskId: string) => `/tasks/${taskId}/runs`,
  run: (runId: string) => `/runs/${runId}`,
  runPlan: (runId: string) => `/runs/${runId}/plan`,
  runToolCalls: (runId: string, cursor?: string) =>
    `/runs/${runId}/tool-calls${cursor ? `?cursor=${cursor}` : ''}`,
  runDiffs: (runId: string) => `/runs/${runId}/diffs`,
  runTests: (runId: string) => `/runs/${runId}/tests`,
  runEventsHistory: (runId: string, afterSeq: number) => `/runs/${runId}/events?after=${afterSeq}`,
  runArtifacts: (runId: string) => `/runs/${runId}/artifacts`,

  // SSE（实时事件流）
  runEventsStream: (runId: string) => `${BASE_STREAM}/runs/${runId}/events`,

  // Approvals
  approvals: (status = 'pending') => `/approvals?status=${status}`,
  resolveApproval: (approvalId: string) => `/approvals/${approvalId}`,

  // Skills
  skills: (query?: { q?: string; category?: string; status?: string; page?: number }) => {
    const params = new URLSearchParams()
    if (query?.q) params.set('q', query.q)
    if (query?.category) params.set('category', query.category)
    if (query?.status) params.set('status', query.status)
    if (query?.page) params.set('page', String(query.page))
    const qs = params.toString()
    return `/skills${qs ? `?${qs}` : ''}`
  },
  skill: (skillId: string) => `/skills/${skillId}`,
  skillVersions: (skillId: string) => `/skills/${skillId}/versions`,
  skillVersionDiff: (skillId: string, a: string, b: string) =>
    `/skills/${skillId}/versions/${a}/diff/${b}`,
  skillRollback: (skillId: string) => `/skills/${skillId}/rollback`,
  skillEvolutions: (skillId: string) => `/skills/${skillId}/evolutions`,
  skillEvaluations: (skillId: string) => `/skills/${skillId}/evaluations`,
  skillUsages: (skillId: string, cursor?: string) =>
    `/skills/${skillId}/usages${cursor ? `?cursor=${cursor}` : ''}`,
  skillCandidates: (status = 'pending') => `/skills/candidates?status=${status}`,
  reviewCandidate: (candidateId: string) => `/skills/candidates/${candidateId}/review`,

  // Context / Memory
  contextSessions: (limit = 20) => `/context/sessions?limit=${limit}`,
  contextSession: (sessionId: string) => `/context/sessions/${sessionId}`,
  contextSummaries: (cursor?: string) => `/context/summaries${cursor ? `?cursor=${cursor}` : ''}`,
  memory: (query?: { layer?: string; page?: number }) => {
    const params = new URLSearchParams()
    if (query?.layer) params.set('layer', query.layer)
    if (query?.page) params.set('page', String(query.page))
    const qs = params.toString()
    return `/memory${qs ? `?${qs}` : ''}`
  },
  memorySearch: '/memory/search',

  // Workflow
  runs: (query?: { status?: string; q?: string; page?: number }) => {
    const params = new URLSearchParams()
    if (query?.status) params.set('status', query.status)
    if (query?.q) params.set('q', query.q)
    if (query?.page) params.set('page', String(query.page))
    const qs = params.toString()
    return `/runs${qs ? `?${qs}` : ''}`
  },
  workflowGraph: (runId: string) => `/workflow/runs/${runId}/graph`,
  workflowTemplate: '/workflow/template',

  // Evaluation
  evalOverview: (range: '7d' | '30d' | '90d') => `/eval/overview?range=${range}`,
  evalModels: (range: string) => `/eval/models?range=${range}`,
  evalSkills: (range: string) => `/eval/skills?range=${range}`,
  evalCompression: (range: string) => `/eval/compression?range=${range}`,
  evalRuns: (page = 1) => `/eval/runs?page=${page}`,

  // Settings
  settingsModels: '/settings/models',
  settingsModelsTest: '/settings/models/test',
  settingsRouting: '/settings/routing',
  settingsMcp: '/settings/mcp',
  settingsMcpServer: (serverId: string) => `/settings/mcp/${serverId}`,
  settingsMcpDiscover: (serverId: string) => `/settings/mcp/${serverId}/discover`,
  settingsPermissions: '/settings/permissions',
  settingsSystem: '/settings/system',
} as const

/** SSE 是相对当前 origin 的 EventSource 路径（不带 /api/v1 之外的 host） */
const BASE_STREAM = ''
