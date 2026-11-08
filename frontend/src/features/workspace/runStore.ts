import { create } from 'zustand'
import type { SseEvent } from '@/api/sse'
import type {
  Approval,
  CodeDiff,
  ContextSession,
  Message,
  Plan,
  TaskStatus,
  TestResult,
  ToolCall,
} from '@/types/api'

/**
 * Run 事件流状态：SSE 事件归一化后入库（docs/06 §4.2）。
 * Workspace 与 Workflow（P2）消费同一事件流，重连回放靠 id 去重保证幂等。
 */

export type StreamStatus = 'connecting' | 'live' | 'down' | 'idle'

export interface RunState {
  messages: Message[]
  plan: Plan | null
  toolCalls: ToolCall[]
  diffs: CodeDiff[]
  tests: TestResult[]
  approvals: Approval[]
  context: ContextSession | null
  runStatus: TaskStatus | null
  summary: string | null
  lastSeq: number
}

interface RunStore {
  runId: string | null
  stream: StreamStatus
  state: RunState
  initRun: (runId: string) => void
  setStream: (s: StreamStatus) => void
  applyEvent: (e: SseEvent) => void
  /** 终态任务的 REST 历史一次性灌入（与流式事件同构） */
  seedHistory: (seed: Partial<Pick<RunState, 'messages' | 'plan' | 'toolCalls' | 'diffs' | 'tests'>>) => void
}

const emptyRun = (): RunState => ({
  messages: [],
  plan: null,
  toolCalls: [],
  diffs: [],
  tests: [],
  approvals: [],
  context: null,
  runStatus: null,
  summary: null,
  lastSeq: 0,
})

function upsertById<T extends { id: string }>(list: T[], item: T): T[] {
  const idx = list.findIndex((x) => x.id === item.id)
  if (idx === -1) return [...list, item]
  const next = [...list]
  next[idx] = item
  return next
}

export const useRunStore = create<RunStore>()((set) => ({
  runId: null,
  stream: 'idle',
  state: emptyRun(),

  initRun: (runId) => {
    if (useRunStore.getState().runId === runId) return
    set({ runId, stream: 'connecting', state: emptyRun() })
  },

  setStream: (stream) => set({ stream }),

  seedHistory: (seed) =>
    set((s) => ({
      state: {
        ...s.state,
        messages: seed.messages ?? s.state.messages,
        plan: seed.plan ?? s.state.plan,
        toolCalls: seed.toolCalls ?? s.state.toolCalls,
        diffs: seed.diffs ?? s.state.diffs,
        tests: seed.tests ?? s.state.tests,
      },
    })),

  applyEvent: (e) =>
    set((s) => {
      if (e.data.runId !== s.runId) return s
      const st = s.state
      const next: RunState = { ...st, lastSeq: Math.max(st.lastSeq, e.id) }
      const p = e.data.payload as Record<string, unknown>

      switch (e.event) {
        case 'run.status':
          next.runStatus = (p as { status: TaskStatus }).status
          break
        case 'plan.updated':
          next.plan = (p as { plan: Plan }).plan
          break
        case 'message.created': {
          const msg = (p as { message: Message }).message
          if (!st.messages.some((m) => m.id === msg.id)) next.messages = [...st.messages, msg]
          break
        }
        case 'tool.call.started':
        case 'tool.call.completed': {
          const call = (p as { toolCall: ToolCall }).toolCall
          next.toolCalls = upsertById(st.toolCalls, call)
          break
        }
        case 'code.diff.created': {
          const diff = (p as { diff: CodeDiff }).diff
          next.diffs = upsertById(st.diffs, diff)
          break
        }
        case 'test.finished': {
          const result = (p as { result: TestResult }).result
          next.tests = upsertById(st.tests, result)
          break
        }
        case 'approval.requested': {
          const approval = (p as { approval: Approval }).approval
          next.approvals = upsertById(st.approvals, approval)
          break
        }
        case 'approval.resolved': {
          const { approvalId, status } = p as { approvalId: string; status: Approval['status'] }
          next.approvals = st.approvals.map((a) =>
            a.id === approvalId ? { ...a, status, resolvedAt: new Date().toISOString() } : a,
          )
          break
        }
        case 'context.updated':
          next.context = (p as { session: ContextSession }).session
          break
        case 'run.completed':
          next.summary = (p as { summary?: string }).summary ?? '任务已完成'
          break
        case 'run.failed':
          next.summary = (p as { error?: string }).error ?? '任务失败'
          break
        default:
          break
      }
      return { state: next }
    }),
}))

/** 时间线视图模型：消息/工具/代码/测试/审批按时间合并排序 */
export type TimelineKind = 'message' | 'tool' | 'diff' | 'test' | 'approval'

export interface TimelineItem {
  key: string
  kind: TimelineKind
  at: number
  message?: Message
  toolCall?: ToolCall
  diff?: CodeDiff
  test?: TestResult
  approval?: Approval
}

export function buildTimeline(st: RunState, filter: 'all' | TimelineKind): TimelineItem[] {
  const items: TimelineItem[] = [
    ...st.messages.map((m) => ({ key: `m_${m.id}`, kind: 'message' as const, at: Date.parse(m.createdAt), message: m })),
    ...st.toolCalls.map((t) => ({ key: `t_${t.id}`, kind: 'tool' as const, at: Date.parse(t.createdAt), toolCall: t })),
    ...st.diffs.flatMap((d) =>
      d.files.map((f, i) => ({ key: `d_${d.id}_${i}`, kind: 'diff' as const, at: Date.parse(d.createdAt), diff: { ...d, files: [f] } })),
    ),
    ...st.tests.map((t) => ({ key: `t_${t.id}`, kind: 'test' as const, at: Date.parse(t.createdAt), test: t })),
    ...st.approvals.map((a) => ({ key: `a_${a.id}`, kind: 'approval' as const, at: Date.parse(a.createdAt), approval: a })),
  ]
  const filtered = filter === 'all' ? items : items.filter((i) => i.kind === filter)
  return filtered.sort((a, b) => a.at - b.at)
}
