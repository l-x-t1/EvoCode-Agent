import { http, HttpResponse } from 'msw'
import { historyForTask, seedRunFor, emptyPage } from '../fixtures/tasks'
import { addTask, getTask, getTasks, isTerminal, updateTask } from '../state'
import { cancelRuntime, ensureRuntime, runtimeByApproval, resolveApproval, subscribeStream } from '../eventPlayer'

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
const notFound = (msg: string) =>
  HttpResponse.json({ error: { code: 'not_found', message: msg } }, { status: 404 })

/** Tasks / Runs / Approvals 域 handlers（含 SSE 事件流端点，docs/06 §3.2/3.3） */
export const taskHandlers = [
  http.get('*/api/v1/tasks/:taskId', async ({ params }) => {
    await wait(150)
    const t = getTask(String(params.taskId))
    return t ? HttpResponse.json(t) : notFound('任务不存在')
  }),

  http.post('*/api/v1/tasks', async ({ request }) => {
    await wait(300)
    const body = (await request.json()) as { title: string; description?: string; repo?: string }
    if (!body?.title?.trim()) {
      return HttpResponse.json(
        { error: { code: 'invalid_request', message: '任务标题不能为空' } },
        { status: 400 },
      )
    }
    const id = `task_${Date.now().toString(36)}`
    const now = new Date().toISOString()
    const runId = `run_${Date.now().toString(36)}`
    const task = {
      id,
      title: body.title.trim().slice(0, 80),
      description: body.description?.trim() ?? body.title.trim(),
      repo: body.repo,
      status: 'queued' as const,
      model: 'auto' as const,
      skillIds: [],
      createdAt: now,
      updatedAt: now,
      stats: { durationMs: 0, tokensIn: 0, tokensOut: 0, toolCalls: 0 },
      latestRunId: runId,
    }
    addTask(task)
    return HttpResponse.json(task, { status: 201 })
  }),

  http.post('*/api/v1/tasks/:taskId/cancel', async ({ params }) => {
    await wait(200)
    const t = getTask(String(params.taskId))
    if (!t) return notFound('任务不存在')
    if (isTerminal(t.status)) {
      return HttpResponse.json(
        { error: { code: 'conflict', message: '任务已结束，无法取消' } },
        { status: 409 },
      )
    }
    const rt = ensureRuntime(t, (patch) => void updateTask(t.id, patch))
    cancelRuntime(rt)
    return HttpResponse.json({ ok: true })
  }),

  http.get('*/api/v1/tasks/:taskId/messages', async ({ params }) => {
    await wait(150)
    const t = getTask(String(params.taskId))
    if (!t) return notFound('任务不存在')
    if (isTerminal(t.status)) {
      const h = historyForTask(t.id)
      return HttpResponse.json(emptyPage(h.messages))
    }
    return HttpResponse.json(emptyPage([]))
  }),

  http.get('*/api/v1/tasks/:taskId/runs', async ({ params }) => {
    const t = getTask(String(params.taskId))
    if (!t) return notFound('任务不存在')
    return HttpResponse.json(emptyPage([seedRunFor(t)]))
  }),

  http.get('*/api/v1/runs/:runId/plan', async ({ params }) => {
    await wait(150)
    const t = getTasks().find((x) => x.latestRunId === String(params.runId))
    if (!t) return notFound('运行不存在')
    if (isTerminal(t.status)) {
      return HttpResponse.json(historyForTask(t.id).plan)
    }
    return HttpResponse.json(null)
  }),

  http.get('*/api/v1/runs/:runId/tool-calls', async ({ params }) => {
    const t = getTasks().find((x) => x.latestRunId === String(params.runId))
    if (!t) return notFound('运行不存在')
    if (isTerminal(t.status)) {
      return HttpResponse.json(emptyPage(historyForTask(t.id).toolCalls))
    }
    return HttpResponse.json(emptyPage([]))
  }),

  http.get('*/api/v1/runs/:runId/diffs', async ({ params }) => {
    const t = getTasks().find((x) => x.latestRunId === String(params.runId))
    if (!t) return notFound('运行不存在')
    if (isTerminal(t.status)) {
      return HttpResponse.json({ items: historyForTask(t.id).diffs })
    }
    return HttpResponse.json({ items: [] })
  }),

  http.get('*/api/v1/runs/:runId/tests', async ({ params }) => {
    const t = getTasks().find((x) => x.latestRunId === String(params.runId))
    if (!t) return notFound('运行不存在')
    if (isTerminal(t.status)) {
      return HttpResponse.json({ items: historyForTask(t.id).tests })
    }
    return HttpResponse.json({ items: [] })
  }),

  // ── SSE 事件流（docs/06 §4）：支持 Last-Event-ID / ?after= 续传 ──
  http.get('*/api/v1/runs/:runId/events', ({ params, request }) => {
    const runId = String(params.runId)
    const url = new URL(request.url)
    const afterRaw = url.searchParams.get('after') ?? request.headers.get('Last-Event-ID') ?? '0'
    const after = Number(afterRaw) || 0

    const task = getTasks().find((x) => x.latestRunId === runId)
    if (!task) return notFound('运行不存在')

    const rt = ensureRuntime(task, (patch) => void updateTask(task.id, patch))
    const stream = subscribeStream(rt, after)
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
      },
    })
  }),

  // ── 审批 ──
  http.get('*/api/v1/approvals', async () => {
    await wait(150)
    return HttpResponse.json(emptyPage([]))
  }),

  http.post('*/api/v1/approvals/:approvalId', async ({ params, request }) => {
    await wait(250)
    const body = (await request.json()) as { decision: 'approved' | 'rejected' }
    const rt = runtimeByApproval(String(params.approvalId))
    if (!rt) return notFound('审批不存在或已处理')
    resolveApproval(rt, String(params.approvalId), body.decision)
    return HttpResponse.json({ ok: true, status: body.decision })
  }),
]
