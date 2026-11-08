import type { Task } from '@/types/api'
import { SEED_TASKS } from './fixtures/tasks'

/**
 * Mock 内存状态：handlers 与剧本引擎共享，保证
 * Dashboard 汇总 / 任务列表 / Workspace 流式执行 三者自洽。
 */
let tasks: Task[] = [...SEED_TASKS]

export function getTasks(): Task[] {
  return tasks
}

export function getTask(id: string): Task | undefined {
  return tasks.find((t) => t.id === id)
}

export function findTaskByRunId(runId: string): Task | undefined {
  return tasks.find((t) => t.latestRunId === runId)
}

export function updateTask(id: string, patch: Partial<Task>): Task | undefined {
  const t = tasks.find((x) => x.id === id)
  if (!t) return undefined
  Object.assign(t, patch, { updatedAt: new Date().toISOString() })
  return t
}

export function addTask(t: Task): void {
  tasks = [t, ...tasks]
}

/** 终态任务不再重放剧本 */
export function isTerminal(status: Task['status']): boolean {
  return ['completed', 'failed', 'cancelled'].includes(status)
}
