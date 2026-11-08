import { http, HttpResponse } from 'msw'
import {
  AGENT_STATUS_FIXTURE,
  SKILL_EVENTS_FIXTURE,
  SUMMARY_FIXTURE,
  buildTrends,
} from '../fixtures/dashboard'
import { getTasks, updateTask } from '../state'

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** Dashboard 域 handlers：汇总数字与运行中任务实时联动 */
export const dashboardHandlers = [
  http.get('*/api/v1/dashboard/summary', async () => {
    await wait(200)
    const tasks = getTasks()
    const running = tasks.filter((t) =>
      ['queued', 'planning', 'executing', 'reviewing', 'waiting_approval'].includes(t.status),
    ).length
    const today = tasks.filter((t) => Date.now() - new Date(t.createdAt).getTime() < 86_400_000).length
    return HttpResponse.json({
      ...SUMMARY_FIXTURE,
      tasksRunning: running,
      tasksToday: today,
    })
  }),

  http.get('*/api/v1/dashboard/trends', async ({ request }) => {
    await wait(300)
    const range = new URL(request.url).searchParams.get('range') ?? '14d'
    const trends = buildTrends()
    const n = range === '7d' ? 7 : range === '30d' ? 30 : 14
    return HttpResponse.json({
      range,
      taskTrend: trends.taskTrend.slice(-n),
      tokenTrend: trends.tokenTrend.slice(-n),
    })
  }),

  http.get('*/api/v1/agents/status', async () => {
    await wait(200)
    const tasks = getTasks()
    const waiting = tasks.filter((t) => t.status === 'waiting_approval').length
    const running = tasks.filter((t) =>
      ['planning', 'executing', 'reviewing'].includes(t.status),
    ).length
    const items = [
      { name: '运行中', value: running },
      { name: '等待审批', value: waiting },
      { name: '空闲', value: Math.max(AGENT_STATUS_FIXTURE.total - running - waiting, 0) },
    ]
    return HttpResponse.json({ total: AGENT_STATUS_FIXTURE.total, items })
  }),

  http.get('*/api/v1/skills/events', async () => {
    await wait(250)
    return HttpResponse.json({ items: SKILL_EVENTS_FIXTURE })
  }),

  http.get('*/api/v1/tasks', async () => {
    await wait(180)
    const tasks = [...getTasks()].sort(
      (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    )
    return HttpResponse.json({ items: tasks, total: tasks.length, page: 1, size: tasks.length })
  }),

  http.put('*/api/v1/tasks/:taskId', async ({ params, request }) => {
    const updated = updateTask(String(params.taskId), (await request.json()) as Record<string, never>)
    if (!updated) return HttpResponse.json({ error: { code: 'not_found', message: '任务不存在' } }, { status: 404 })
    return HttpResponse.json(updated)
  }),
]
