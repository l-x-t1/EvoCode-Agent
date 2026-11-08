import { MessagesSquare, ListTree, ScrollText } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { MockBadge } from '@/components/common/MockBadge'
import { PageSkeleton } from '@/components/common/PageSkeleton'
import { useApi } from '@/hooks/useApi'
import { useSearchParamsState } from '@/hooks/useSearchParamsState'
import { cn } from '@/lib/utils'
import type { Task } from '@/types/api'
import { cancelTask, fetchDiffs, fetchMessages, fetchPlan, fetchTask, fetchTests, fetchToolCalls } from './api'
import { useRunStore } from './runStore'
import { useRunStream } from './useRunStream'
import { ConversationPanel } from './components/ConversationPanel'
import { EventTimeline } from './components/EventTimeline'
import { NewTaskForm } from './components/NewTaskForm'
import { PlanPanel } from './components/PlanPanel'
import { TaskHeader } from './components/TaskHeader'
import { TaskListDrawer } from './components/TaskListDrawer'

const TERMINAL = ['completed', 'failed', 'cancelled']
const MOBILE_PANELS = [
  { key: 'conv', label: '会话', icon: MessagesSquare },
  { key: 'timeline', label: '时间线', icon: ListTree },
  { key: 'plan', label: '计划', icon: ScrollText },
] as const

export default function WorkspacePage() {
  const { taskId } = useParams()
  const [panel, setPanel] = useSearchParamsState('panel', 'timeline')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)

  const runState = useRunStore((s) => s.state)
  const seedHistory = useRunStore((s) => s.seedHistory)

  const { data: task, loading: taskLoading } = useApi(
    () => (taskId ? fetchTask(taskId) : Promise.resolve(null)),
    [taskId],
  )
  const runId = task?.latestRunId

  // SSE 订阅（运行中任务驱动全页；终态任务仅保持连接）
  useRunStream(runId)

  // 终态任务：REST 历史一次性灌入（与流式事件同构，docs/06 §5）
  useEffect(() => {
    if (!task || !runId || !TERMINAL.includes(task.status)) return
    let cancelled = false
    void (async () => {
      const [messages, plan, toolCalls, diffs, tests] = await Promise.all([
        fetchMessages(task.id).catch(() => null),
        fetchPlan(runId).catch(() => null),
        fetchToolCalls(runId).catch(() => null),
        fetchDiffs(runId).catch(() => null),
        fetchTests(runId).catch(() => null),
      ])
      if (cancelled) return
      seedHistory({
        messages: messages?.items ?? [],
        plan: plan ?? undefined,
        toolCalls: toolCalls?.items ?? [],
        diffs: diffs?.items ?? [],
        tests: tests?.items ?? [],
      })
      useRunStore.setState((s) =>
        s.state.runStatus ? s : { state: { ...s.state, runStatus: task.status, summary: '历史执行记录' } },
      )
    })()
    return () => {
      cancelled = true
    }
  }, [task?.id, task?.status, runId, seedHistory, task])

  // 无任务 → 空态：新建入口 + 全部任务列表（验收 M5）
  if (!taskId) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <div className="mb-4 flex items-center gap-2">
          <h1 className="text-2xl font-semibold text-foreground">Agent Workspace</h1>
          <MockBadge />
        </div>
        <NewTaskForm />
      </div>
    )
  }

  if (taskLoading || !task) {
    return <PageSkeleton />
  }

  const pendingApprovals = runState.approvals.filter((a) => a.status === 'pending').length
  const active = !TERMINAL.includes(task.status)
  // 流式 run.status 优先于 REST 快照，保证头部状态实时（docs/06 §4.2）
  const effectiveTask: Task = runState.runStatus ? { ...task, status: runState.runStatus } : task
  const mobilePanel = (['conv', 'timeline', 'plan'].includes(panel) ? panel : 'timeline') as
    | 'conv'
    | 'timeline'
    | 'plan'

  // 全高页面：flex-1 + min-h-0 占满 main 剩余高度（M7，去除 calc 魔法数字）
  return (
    <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col gap-3">
      <TaskHeader
        task={effectiveTask}
        onOpenList={() => setDrawerOpen(true)}
        onCancel={() => setCancelOpen(true)}
      />

      {/* 移动端三段切换（docs/02 §5） */}
      <div className="flex shrink-0 rounded-lg border border-border bg-surface p-0.5 lg:hidden" role="tablist" aria-label="面板切换">
        {MOBILE_PANELS.map((p) => (
          <button
            key={p.key}
            type="button"
            role="tab"
            aria-selected={mobilePanel === p.key}
            onClick={() => setPanel(p.key)}
            className={cn(
              'flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-xs transition-colors',
              mobilePanel === p.key
                ? 'bg-elevated font-medium text-foreground'
                : 'text-foreground-secondary hover:text-foreground',
            )}
          >
            <p.icon className="size-3.5" aria-hidden="true" />
            {p.label}
          </button>
        ))}
      </div>

      {/* 三栏（docs/05 §2 线框）：<lg 单列切换；lg 双栏；xl 三栏（窄侧栏）；2xl 宽栏。
          行高 minmax(0,1fr) 保证三栏可收缩、内部滚动（M7）。 */}
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-3 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[270px_minmax(0,1fr)_290px] 2xl:grid-cols-[330px_minmax(0,1fr)_360px]">
        <div className={cn('min-h-0', mobilePanel === 'conv' ? 'block' : 'hidden', 'lg:block')}>
          {/* 终态任务输入一律禁用（验收 M4：不做假交互） */}
          <ConversationPanel
            messages={runState.messages}
            locked
            placeholder={
              active ? '任务执行中，插话功能将在后续阶段开放' : '任务已结束。追问与重跑将在后续阶段支持'
            }
          />
        </div>
        <div className={cn('min-h-0', mobilePanel === 'timeline' ? 'block' : 'hidden lg:block')}>
          <EventTimeline />
        </div>
        <div className={cn('min-h-0', mobilePanel === 'plan' ? 'block' : 'hidden xl:block')}>
          <PlanPanel
            plan={runState.plan}
            context={runState.context}
            diffs={runState.diffs}
            pendingApprovals={pendingApprovals}
            onGotoApprovals={() => setPanel('timeline')}
          />
        </div>
      </div>

      <TaskListDrawer open={drawerOpen} onOpenChange={setDrawerOpen} currentTaskId={task.id} />

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="取消当前任务？"
        description="正在执行的步骤将停止，已完成的部分会保留在执行记录中。"
        confirmLabel="取消任务"
        danger
        onConfirm={() => {
          void (async () => {
            try {
              await cancelTask(task.id)
              toast.success('已发送取消请求')
            } catch (err) {
              toast.error(err instanceof Error ? err.message : '取消失败')
            }
          })()
        }}
      />
    </div>
  )
}
