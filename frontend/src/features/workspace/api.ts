import { request } from '@/api/client'
import { endpoints } from '@/api/endpoints'
import type { CodeDiff, Message, Page, Plan, Task, TestResult, ToolCall } from '@/types/api'

export const fetchTasks = () => request<Page<Task>>(endpoints.tasks())

export const fetchTask = (taskId: string) => request<Task>(endpoints.task(taskId))

export const createTask = (body: { title: string; description?: string; repo?: string }) =>
  request<Task>(endpoints.createTask, { method: 'POST', body })

export const cancelTask = (taskId: string) =>
  request<{ ok: boolean }>(endpoints.cancelTask(taskId), { method: 'POST' })

export const fetchMessages = (taskId: string) =>
  request<Page<Message>>(endpoints.taskMessages(taskId))

export const fetchPlan = (runId: string) =>
  request<Plan | null>(endpoints.runPlan(runId))

export const fetchToolCalls = (runId: string) =>
  request<Page<ToolCall>>(endpoints.runToolCalls(runId))

export const fetchDiffs = (runId: string) =>
  request<{ items: CodeDiff[] }>(endpoints.runDiffs(runId))

export const fetchTests = (runId: string) =>
  request<{ items: TestResult[] }>(endpoints.runTests(runId))
