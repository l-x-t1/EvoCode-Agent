import type {
  Approval,
  CodeDiff,
  ContextSession,
  Message,
  Plan,
  Task,
  TestResult,
  ToolCall,
} from '@/types/api'

/**
 * SSE 剧本引擎（docs/04 §5）：
 * - 按剧本逐步派发事件帧（docs/06 §4 协议）
 * - approval.requested 后真实暂停，等待 POST /approvals/:id 决策后走不同分支
 * - 事件帧全部落 history，重连时按 lastEventId 续传（模拟 Last-Event-ID）
 */

const nowIso = () => new Date().toISOString()
const sleepRaw = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

interface Subscriber {
  enqueue(frame: string): void
}

class CancelledError extends Error {}

export interface ScenarioCtx {
  emit(event: string, payload: unknown): void
  waitForApproval(approval: Approval): Promise<'approved' | 'rejected'>
  sleep(ms: number): Promise<void>
}

interface Runtime {
  runId: string
  seq: number
  history: { seq: number; frame: string }[]
  subscribers: Set<Subscriber>
  started: boolean
  finished: boolean
  cancelled: boolean
  task: Task
  onUpdateTask: (patch: Partial<Task>) => void
}

const runtimes = new Map<string, Runtime>()
const approvalToRuntime = new Map<string, Runtime>()

function encodeFrame(seq: number, event: string, data: unknown): string {
  return `event: ${event}\nid: ${seq}\ndata: ${JSON.stringify(data)}\n\n`
}

function emit(rt: Runtime, event: string, payload: unknown): void {
  const seq = ++rt.seq
  const envelope = { v: 1, seq, ts: nowIso(), runId: rt.runId, payload }
  const frame = encodeFrame(seq, event, envelope)
  rt.history.push({ seq, frame })
  for (const sub of rt.subscribers) sub.enqueue(frame)

  // 副作用：同步内存中的任务状态，保证 Dashboard 列表与剧本一致
  if (event === 'run.status') {
    const status = (payload as { status: Task['status'] }).status
    rt.onUpdateTask({ status, updatedAt: nowIso() })
    if (['completed', 'failed', 'cancelled'].includes(status)) rt.finished = true
  }
  if (event === 'run.completed') {
    const stats = (payload as { stats: Task['stats'] }).stats
    rt.onUpdateTask({ stats, updatedAt: nowIso() })
  }
}

/** 确保运行时存在；任务仍可重放（从头播放剧本） */
export function ensureRuntime(task: Task, onUpdateTask: (patch: Partial<Task>) => void): Runtime {
  const runId = task.latestRunId ?? `run_${task.id}`
  let rt = runtimes.get(runId)
  if (!rt) {
    rt = {
      runId,
      seq: 0,
      history: [],
      subscribers: new Set(),
      started: false,
      finished: false,
      cancelled: false,
      task,
      onUpdateTask,
    }
    runtimes.set(runId, rt)
  }
  return rt
}

export function runtimeByApproval(approvalId: string): Runtime | undefined {
  return approvalToRuntime.get(approvalId)
}

/** 订阅事件流：先补发 history 中 seq > lastEventId 的帧，再接收实时帧（15s 心跳保活） */
export function subscribeStream(rt: Runtime, lastEventId: number): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  let sub: Subscriber | null = null
  let heartbeat: ReturnType<typeof setInterval> | null = null
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const h of rt.history) {
        if (h.seq > lastEventId) controller.enqueue(enc.encode(h.frame))
      }
      sub = {
        enqueue: (frame) => {
          try {
            controller.enqueue(enc.encode(frame))
          } catch {
            /* 订阅方已断开 */
          }
        },
      }
      rt.subscribers.add(sub)
      heartbeat = setInterval(() => sub?.enqueue(': ping\n\n'), 15_000)
      const shouldPlay = !rt.started && !rt.cancelled && !rt.finished && !isTerminalStatus(rt.task.status)
      if (shouldPlay) {
        rt.started = true
        void playScenario(rt)
      }
    },
    cancel() {
      if (heartbeat) clearInterval(heartbeat)
      if (sub) rt.subscribers.delete(sub)
    },
  })
}

function isTerminalStatus(status: Runtime['task']['status']): boolean {
  return ['completed', 'failed', 'cancelled'].includes(status)
}

export function cancelRuntime(rt: Runtime): void {
  rt.cancelled = true
  if (!rt.finished) emit(rt, 'run.status', { status: 'cancelled', finishedAt: nowIso() })
}

export function resolveApproval(rt: Runtime, approvalId: string, decision: 'approved' | 'rejected'): void {
  emit(rt, 'approval.resolved', { approvalId, status: decision })
  const waiter = (rt as Runtime & { approvalWaiter?: (d: 'approved' | 'rejected') => void }).approvalWaiter
  if (waiter) {
    ;(rt as Runtime & { approvalWaiter?: (d: 'approved' | 'rejected') => void }).approvalWaiter = undefined
    waiter(decision)
  }
}

// ── 剧本 ─────────────────────────────────────────────

async function playScenario(rt: Runtime): Promise<void> {
  const ctx: ScenarioCtx = {
    emit: (event, payload) => emit(rt, event, payload),
    sleep: async (ms) => {
      await sleepRaw(ms)
      if (rt.cancelled) throw new CancelledError()
    },
    waitForApproval: (approval) =>
      new Promise((resolve) => {
        approvalToRuntime.set(approval.id, rt)
        ;(rt as Runtime & { approvalWaiter?: (d: 'approved' | 'rejected') => void }).approvalWaiter = resolve
        emit(rt, 'approval.requested', { approval })
      }),
  }
  try {
    await script(ctx, rt)
  } catch (err) {
    if (!(err instanceof CancelledError)) {
      emit(rt, 'run.failed', { stats: rt.task.stats, error: String(err) })
    }
  }
}

let idSeq = 100
const uid = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${idSeq++}`

function message(runId: string, role: Message['role'], content: string): { message: Message } {
  return { message: { id: uid('msg'), runId, role, content, createdAt: nowIso() } }
}

function toolCall(
  runId: string,
  server: string,
  tool: string,
  args: Record<string, unknown>,
  risk: ToolCall['risk'],
  stepId: string,
): ToolCall {
  return { id: uid('tc'), runId, stepId, server, tool, args, status: 'running', risk, createdAt: nowIso() }
}

function completeCall(call: ToolCall, resultSummary: string, durationMs: number): { toolCall: ToolCall } {
  return { toolCall: { ...call, status: 'succeeded', resultSummary, durationMs } }
}

/** 主剧本：修复单测（含测试失败 → 修复 → 通过 → 危险操作审批 → 分支） */
async function script(ctx: ScenarioCtx, rt: Runtime): Promise<void> {
  const runId = rt.runId
  const t = rt.task
  const fast = t.id === 'task_02' // 短剧本（flaky 排查）

  ctx.emit('run.status', { status: 'planning' })
  ctx.emit('message.created', message(runId, 'user', t.description || t.title))
  await ctx.sleep(900)

  const steps: Plan['steps'] = fast
    ? [
        { id: 's1', index: 1, title: '拉取最近 20 次 CI 构建日志', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
        { id: 's2', index: 2, title: '归纳失败模式并修复时序依赖', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
        { id: 's3', index: 3, title: '推送修复分支触发 CI 验证', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
      ]
    : [
        { id: 's1', index: 1, title: '定位失败测试与相关源码', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
        { id: 's2', index: 2, title: '修复断言并补充边界用例', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
        { id: 's3', index: 3, title: '容器内执行测试回归', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
        { id: 's4', index: 4, title: '推送变更分支并生成报告', agent: 'executor', status: 'pending', attempt: 1, toolCallIds: [] },
      ]

  const plan: Plan = { id: uid('plan'), runId, revision: 1, steps }
  ctx.emit(
    'message.created',
    message(
      runId,
      'planner',
      fast
        ? '计划三步：先拉取构建日志归纳失败规律，再修复时序依赖，最后推送分支交由 CI 验证。'
        : '计划四步：定位失败用例 → 修复断言并补边界用例 → 沙箱回归 → 推送分支。回归通过后才会请求推送授权。',
    ),
  )
  ctx.emit('plan.updated', { plan })
  ctx.emit('run.status', { status: 'executing' })
  ctx.emit('context.updated', { session: ctxSession(runId, 0.22) })
  await ctx.sleep(700)

  // s1
  plan.steps[0] = { ...plan.steps[0], status: 'running' }
  ctx.emit('plan.updated', { plan })
  const c1 = toolCall(runId, fast ? 'git' : 'filesystem', fast ? 'ci_logs' : 'read_file', fast ? { branch: 'main', limit: 20 } : { path: 'src/services/user.test.ts', lines: [1, 80] }, 'safe', 's1')
  ctx.emit('tool.call.started', { toolCall: c1 })
  await ctx.sleep(900)
  ctx.emit('tool.call.completed', completeCall(c1, fast ? '20 次构建中 6 次失败，均卡在 checkout 锁竞争' : '读取成功：activateUser 相关 2 个失败用例位于 L34-L61', 260))
  ctx.emit('context.updated', { session: ctxSession(runId, 0.38) })
  await ctx.sleep(600)

  // s2
  plan.steps[0] = { ...plan.steps[0], status: 'done' }
  plan.steps[1] = { ...plan.steps[1], status: 'running' }
  ctx.emit('plan.updated', { plan })
  ctx.emit('message.created', message(runId, 'executor', fast ? '失败集中于并行用例共享 checkout 锁；准备为该流程加独立锁命名空间。' : '根因：activateUser 乐观锁更新后未刷新返回对象，断言使用了过期状态。修复并补充 2 个边界用例。'))

  const c2 = toolCall(runId, 'filesystem', 'write_file', { path: fast ? 'src/flows/checkout.ts' : 'src/services/user.ts' }, 'safe', 's2')
  ctx.emit('tool.call.started', { toolCall: c2 })
  await ctx.sleep(1100)
  ctx.emit('tool.call.completed', completeCall(c2, fast ? '写入修复（+12 −4）' : '写入修复与新增用例（+34 −8）', 980))
  ctx.emit('code.diff.created', {
    diff: {
      id: uid('diff'),
      runId,
      createdAt: nowIso(),
      files: fast
        ? [{ path: 'src/flows/checkout.ts', additions: 12, deletions: 4, patch: '@@ -88,7 +88,9 @@\n-  const lock = getLock(\'checkout\')\n+  // 并行用例共享锁导致随机失败：按租户隔离\n+  const lock = getLock(`checkout:${tenantId}`)\n   await lock.acquire()' }]
        : [
            { path: 'src/services/user.ts', additions: 6, deletions: 2, patch: '@@ -104,7 +104,9 @@\n   const updated = await repo.save(user)\n-  return user\n+  // 返回刷新后的对象，避免断言读到过期状态\n+  return repo.reload(updated)' },
            { path: 'src/services/user.test.ts', additions: 34, deletions: 8, patch: '@@ -34,9 +34,12 @@\n   it(\'activates pending user\', async () => {\n-    const res = await svc.activate(id)\n-    expect(res.status).toBe(\'pending\')\n+    const res = await svc.activate(id)\n+    expect(res.status).toBe(\'active\')\n   })\n+\n+  it(\'拒绝激活被封禁用户\', async () => {\n+    await expect(svc.activate(bannedId)).rejects.toThrow(BannedError)\n+  })' },
          ],
    } satisfies CodeDiff,
  })
  ctx.emit('context.updated', { session: ctxSession(runId, 0.57) })
  await ctx.sleep(600)

  // s3：回归（失败 → 修复 → 通过）
  const regIdx = fast ? 2 : 2
  plan.steps[1] = { ...plan.steps[1], status: 'done' }
  plan.steps[regIdx] = { ...plan.steps[regIdx], status: 'running' }
  ctx.emit('plan.updated', { plan })

  const c3 = toolCall(runId, 'tests', 'run_tests', { suite: fast ? 'flows/checkout' : 'services/user' }, 'safe', plan.steps[regIdx].id)
  ctx.emit('tool.call.started', { toolCall: c3 })
  await ctx.sleep(1400)
  ctx.emit('tool.call.completed', { toolCall: { ...c3, status: 'succeeded', resultSummary: fast ? '18/20 通过，2 个仍偶发' : '18/20 通过，2 个新用例因缺少种子数据失败', durationMs: 3_420 } })
  ctx.emit('test.finished', {
    result: {
      id: uid('test'), runId, passed: 18, failed: 2, skipped: 0,
      failures: [{ name: 'user.test.ts › 拒绝激活被封禁用户', message: 'Cannot read properties of undefined (reading \'banned\')' }],
      createdAt: nowIso(),
    } satisfies TestResult,
  })
  await ctx.sleep(800)

  ctx.emit('message.created', message(runId, 'executor', fast ? '两个偶发用例仍与锁释放时序相关，补加重试等待。' : '2 个新用例缺少被封禁用户的种子数据，补齐 fixture 后重跑。'))
  const c3b = toolCall(runId, 'filesystem', 'write_file', { path: 'tests/fixtures/users.ts' }, 'safe', plan.steps[regIdx].id)
  ctx.emit('tool.call.started', { toolCall: c3b })
  await ctx.sleep(800)
  ctx.emit('tool.call.completed', completeCall(c3b, '补齐种子数据（+9 −0）', 420))
  ctx.emit('code.diff.created', {
    diff: {
      id: uid('diff'), runId, createdAt: nowIso(),
      files: [{ path: 'tests/fixtures/users.ts', additions: 9, deletions: 0, patch: '@@ -18,3 +18,9 @@\n+export const bannedUser = {\n+  id: \'u_banned\',\n+  status: \'banned\',\n+}' }],
    } satisfies CodeDiff,
  })

  const c3c = toolCall(runId, 'tests', 'run_tests', { suite: plan.steps[regIdx] ? 'services/user' : '' }, 'safe', plan.steps[regIdx].id)
  ctx.emit('tool.call.started', { toolCall: c3c })
  await ctx.sleep(1300)
  ctx.emit('tool.call.completed', completeCall(c3c, '20/20 全部通过', 2_980))
  ctx.emit('test.finished', {
    result: { id: uid('test'), runId, passed: 20, failed: 0, skipped: 0, failures: [], createdAt: nowIso() } satisfies TestResult,
  })
  plan.steps[regIdx] = { ...plan.steps[regIdx], status: 'done' }
  ctx.emit('plan.updated', { plan })
  ctx.emit('context.updated', { session: ctxSession(runId, 0.71) })
  await ctx.sleep(700)

  // s4：危险操作 → 审批 → 分支
  const lastIdx = fast ? 2 : 3
  if (!fast) plan.steps[lastIdx] = { ...plan.steps[lastIdx], status: 'running' }
  ctx.emit('plan.updated', { plan })
  ctx.emit('run.status', { status: 'waiting_approval' })

  const pushCall = toolCall(runId, 'git', 'git_push', { remote: 'origin', branch: fast ? 'fix/flaky-checkout' : 'fix/user-unit-test', force: false }, 'dangerous', plan.steps[lastIdx].id)
  ctx.emit('tool.call.started', { toolCall: pushCall })
  const approval: Approval = {
    id: uid('apv'), runId, toolCallId: pushCall.id, tool: 'git_push',
    summary: `Executor 请求推送 3 个提交到远程仓库 ${fast ? 'fix/flaky-checkout' : 'fix/user-unit-test'} 分支（含 2 个文件修改、1 个新增用例文件）。`,
    risk: 'dangerous', status: 'pending', createdAt: nowIso(),
  }
  const decision = await ctx.waitForApproval(approval)

  if (decision === 'approved') {
    ctx.emit('tool.call.completed', completeCall(pushCall, '推送成功：3 commits → origin', 1_540))
    if (!fast) plan.steps[lastIdx] = { ...plan.steps[lastIdx], status: 'done' }
    ctx.emit('plan.updated', { plan })
    ctx.emit('message.created', message(runId, 'reviewer', fast ? '修复已推送，CI 已触发。本次任务沉淀 1 条 flaky 排查经验进入候选 Skill。' : '变更已推送。回归 20/20 通过，共 4 次工具调用、1 次重试。本次修复经验已提取为候选 Skill「单测修复 v3.3」。'))
    ctx.emit('context.updated', { session: ctxSession(runId, 0.74) })
    ctx.emit('run.completed', {
      stats: { durationMs: 0, tokensIn: 34_600, tokensOut: 12_900, toolCalls: 7, testPassRate: 1 },
      summary: '已修复并通过全部回归，变更已推送。',
    })
    ctx.emit('run.status', { status: 'completed', finishedAt: nowIso() })
  } else {
    ctx.emit('tool.call.completed', { toolCall: { ...pushCall, status: 'cancelled', durationMs: 0 } })
    ctx.emit('message.created', message(runId, 'replanner', '推送被拒绝。修订计划：保留本地变更，跳过推送步骤，改为生成补丁文件与说明。'))
    plan.revision = 2
    if (!fast) plan.steps[lastIdx] = { ...plan.steps[lastIdx], status: 'replanned' }
    plan.steps.push({ id: 's_r1', index: plan.steps.length + 1, title: '生成本地补丁与未推送说明', agent: 'replanner', status: 'running', attempt: 1, toolCallIds: [] })
    ctx.emit('plan.updated', { plan })
    await ctx.sleep(900)
    plan.steps[plan.steps.length - 1] = { ...plan.steps[plan.steps.length - 1], status: 'done' }
    ctx.emit('plan.updated', { plan })
    ctx.emit('message.created', message(runId, 'reviewer', '已生成 fix.patch 与 UNPUSHED.md 说明。本地回归通过，推送动作已按人工决策跳过。'))
    ctx.emit('run.completed', {
      stats: { durationMs: 0, tokensIn: 33_800, tokensOut: 12_100, toolCalls: 6, testPassRate: 1 },
      summary: '本地修复完成，未推送（人工拒绝）。',
    })
    ctx.emit('run.status', { status: 'completed', finishedAt: nowIso() })
  }
}

function ctxSession(runId: string, usedRatio: number): ContextSession {
  const window = 128_000
  const used = Math.round(window * usedRatio)
  return {
    id: `ctx_${runId}`,
    runId,
    windowTokens: window,
    usedTokens: used,
    segments: [
      { key: 'system', tokens: Math.round(used * 0.08) },
      { key: 'skill', tokens: Math.round(used * 0.12) },
      { key: 'memory', tokens: Math.round(used * 0.1) },
      { key: 'history', tokens: Math.round(used * 0.46) },
      { key: 'working', tokens: Math.round(used * 0.24) },
      { key: 'compressed', tokens: 0 },
    ],
    compressionEvents: [],
    updatedAt: nowIso(),
  }
}
