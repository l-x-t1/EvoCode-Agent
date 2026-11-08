import type {
  CodeDiff,
  Message,
  Page,
  Plan,
  Run,
  Task,
  TestResult,
  ToolCall,
} from '@/types/api'

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()

export const RUNNING_TASK_ID = 'task_01'
export const WAITING_TASK_ID = 'task_02'
export const ACTIVE_STATUSES: Task['status'][] = [
  'queued',
  'planning',
  'executing',
  'reviewing',
  'waiting_approval',
]

function task(partial: Partial<Task> & Pick<Task, 'id' | 'title' | 'status'>): Task {
  return {
    description: '',
    model: 'glm-5.3',
    skillIds: [],
    createdAt: hoursAgo(2),
    updatedAt: hoursAgo(2),
    stats: { durationMs: 0, tokensIn: 0, tokensOut: 0, toolCalls: 0 },
    ...partial,
  }
}

/** 种子任务（docs/04 §5 故事线：运行中 / 待审批 / 失败 / 已完成） */
export const SEED_TASKS: Task[] = [
  task({
    id: RUNNING_TASK_ID,
    title: '修复用户模块单测并回归',
    description: 'user.test.ts 中 activateUser 相关的 2 个用例失败，请定位原因、修复断言，跑通全部测试后推送分支。',
    repo: 'acme/order-service',
    status: 'executing',
    createdAt: minsAgo(14),
    updatedAt: minsAgo(1),
    skillIds: ['skill_unittest_fix'],
    latestRunId: 'run_01',
    stats: { durationMs: 752_000, tokensIn: 32_400, tokensOut: 12_800, toolCalls: 5 },
  }),
  task({
    id: WAITING_TASK_ID,
    title: '排查 CI flaky 用例',
    description: 'checkout 流程的集成测试在 CI 上随机失败，本地复现困难，请分析最近 20 次构建日志找出规律并尝试修复。',
    repo: 'acme/order-service',
    status: 'waiting_approval',
    createdAt: minsAgo(9),
    updatedAt: minsAgo(2),
    skillIds: ['skill_flaky_debug'],
    latestRunId: 'run_02',
    stats: { durationMs: 484_000, tokensIn: 21_600, tokensOut: 7_100, toolCalls: 3 },
  }),
  task({
    id: 'task_03',
    title: '为订单服务补充 API 文档',
    description: '根据 routes/ 目录下的路由定义为订单服务补全 API 文档（含参数与响应示例）。',
    repo: 'acme/order-service',
    status: 'completed',
    createdAt: hoursAgo(5),
    updatedAt: hoursAgo(4.8),
    skillIds: ['skill_docs_gen'],
    latestRunId: 'run_03',
    stats: { durationMs: 251_000, tokensIn: 18_900, tokensOut: 24_300, toolCalls: 4 },
  }),
  task({
    id: 'task_04',
    title: '重构权限校验中间件',
    description: '将散落在各路由的权限判断收敛为统一中间件，并保持现有行为不变。',
    repo: 'acme/order-service',
    status: 'failed',
    createdAt: hoursAgo(27),
    updatedAt: hoursAgo(26.6),
    skillIds: [],
    latestRunId: 'run_04',
    stats: { durationMs: 1_300_000, tokensIn: 88_200, tokensOut: 21_400, toolCalls: 11 },
  }),
  task({
    id: 'task_05',
    title: '生成 README 部署章节',
    description: '为仓库 README 补充本地部署与 Docker Compose 启动说明。',
    repo: 'acme/order-service',
    status: 'completed',
    createdAt: hoursAgo(30),
    updatedAt: hoursAgo(29.9),
    skillIds: [],
    latestRunId: 'run_05',
    stats: { durationMs: 182_000, tokensIn: 9_100, tokensOut: 8_400, toolCalls: 2 },
  }),
  task({
    id: 'task_06',
    title: '升级依赖并修复破坏性变更',
    description: '将 express 从 v4 升级到 v5，修复类型与中间件签名的不兼容变更。',
    repo: 'acme/order-service',
    status: 'queued',
    createdAt: minsAgo(1),
    updatedAt: minsAgo(1),
    skillIds: [],
    latestRunId: 'run_06',
    stats: { durationMs: 41_000, tokensIn: 2_300, tokensOut: 900, toolCalls: 0 },
  }),
]

export function seedRunFor(t: Task): Run {
  return {
    id: t.latestRunId ?? `run_${t.id}`,
    taskId: t.id,
    status: t.status,
    startedAt: t.createdAt,
    finishedAt: ['completed', 'failed', 'cancelled'].includes(t.status) ? t.updatedAt : undefined,
    model: t.model === 'auto' ? 'glm-5.3' : t.model,
    stats: { ...t.stats, replanCount: 0 },
  }
}

/** 终态任务的 REST 历史数据（Workspace 非流式加载用） */
export interface TerminalHistory {
  messages: Message[]
  plan: Plan | null
  toolCalls: ToolCall[]
  diffs: CodeDiff[]
  tests: TestResult[]
}

const TERMINAL_HISTORY: Record<string, TerminalHistory> = {
  task_03: {
    messages: [
      {
        id: 'msg_03_1',
        runId: 'run_03',
        role: 'user',
        content: '根据 routes/ 目录下的路由定义为订单服务补全 API 文档（含参数与响应示例）。',
        createdAt: hoursAgo(5),
      },
      {
        id: 'msg_03_2',
        runId: 'run_03',
        role: 'planner',
        content:
          '计划分三步：\n1. 扫描 routes/ 提取全部端点与参数\n2. 按资源分组生成 docs/api.md（含请求/响应示例）\n3. 校验示例与 zod schema 一致',
        createdAt: hoursAgo(5),
        tokens: 320,
      },
      {
        id: 'msg_03_3',
        runId: 'run_03',
        role: 'reviewer',
        content: '文档已生成，共 6 个资源组、23 个端点。示例经 schema 校验全部通过。',
        createdAt: hoursAgo(4.9),
        tokens: 180,
      },
    ],
    plan: {
      id: 'plan_03',
      runId: 'run_03',
      revision: 1,
      steps: [
        { id: 's1', index: 1, title: '扫描 routes/ 提取端点', agent: 'executor', status: 'done', attempt: 1, toolCallIds: ['tc_03_1'] },
        { id: 's2', index: 2, title: '生成 docs/api.md', agent: 'executor', status: 'done', attempt: 1, toolCallIds: ['tc_03_2'] },
        { id: 's3', index: 3, title: '校验示例与 schema 一致', agent: 'reviewer', status: 'done', attempt: 1, toolCallIds: [] },
      ],
    },
    toolCalls: [
      {
        id: 'tc_03_1', runId: 'run_03', server: 'search', tool: 'list_route_files',
        args: { dir: 'src/routes' }, resultSummary: '发现 6 个路由文件、23 个端点',
        status: 'succeeded', risk: 'safe', durationMs: 310, createdAt: hoursAgo(5),
      },
      {
        id: 'tc_03_2', runId: 'run_03', server: 'filesystem', tool: 'write_file',
        args: { path: 'docs/api.md' }, resultSummary: '写入 412 行文档',
        status: 'succeeded', risk: 'safe', durationMs: 890, createdAt: hoursAgo(4.95),
      },
    ],
    diffs: [
      {
        id: 'diff_03', runId: 'run_03', createdAt: hoursAgo(4.95),
        files: [
          {
            path: 'docs/api.md', additions: 412, deletions: 0,
            patch: '@@ -0,0 +1,5 @@\n+# 订单服务 API 文档\n+\n+## 订单\n+\n+### POST /orders\n+创建订单…（示例略）',
          },
        ],
      },
    ],
    tests: [],
  },
  task_04: {
    messages: [
      {
        id: 'msg_04_1', runId: 'run_04', role: 'user',
        content: '将散落在各路由的权限判断收敛为统一中间件，并保持现有行为不变。',
        createdAt: hoursAgo(27),
      },
      {
        id: 'msg_04_2', runId: 'run_04', role: 'executor',
        content: '已完成 9 个路由的收敛改写，正在执行回归测试。',
        createdAt: hoursAgo(26.8), tokens: 540,
      },
      {
        id: 'msg_04_3', runId: 'run_04', role: 'reviewer',
        content:
          '回归未通过：admin 路由组的 3 个用例失败。重试 2 次后仍失败，达到重试上限，任务终止。\n建议：单独排查 admin 组的 ownership 校验逻辑后重新提交。',
        createdAt: hoursAgo(26.6), tokens: 260,
      },
    ],
    plan: {
      id: 'plan_04', runId: 'run_04', revision: 2,
      steps: [
        { id: 's1', index: 1, title: '梳理现有权限判断点', agent: 'executor', status: 'done', attempt: 1, toolCallIds: ['tc_04_1'] },
        { id: 's2', index: 2, title: '实现统一中间件并改写路由', agent: 'executor', status: 'done', attempt: 1, toolCallIds: ['tc_04_2'] },
        { id: 's3', index: 3, title: '全量回归测试', agent: 'executor', status: 'failed', attempt: 3, toolCallIds: ['tc_04_3'] },
        { id: 's4', index: 4, title: '更新文档与变更说明', agent: 'reviewer', status: 'pending', attempt: 1, toolCallIds: [] },
      ],
    },
    toolCalls: [
      {
        id: 'tc_04_1', runId: 'run_04', server: 'search', tool: 'grep_code',
        args: { pattern: 'requireRole\\(', glob: 'src/routes/**' }, resultSummary: '命中 9 个文件、31 处调用',
        status: 'succeeded', risk: 'safe', durationMs: 420, createdAt: hoursAgo(27),
      },
      {
        id: 'tc_04_2', runId: 'run_04', server: 'filesystem', tool: 'write_file',
        args: { path: 'src/middleware/auth.ts' }, resultSummary: '写入统一中间件（148 行），改写 9 个路由',
        status: 'succeeded', risk: 'safe', durationMs: 1_240, createdAt: hoursAgo(26.9),
      },
      {
        id: 'tc_04_3', runId: 'run_04', server: 'tests', tool: 'run_tests',
        args: { suite: 'routes/**' }, resultSummary: '15 通过 / 3 失败（重试 3 次）',
        status: 'failed', risk: 'safe', durationMs: 96_000, createdAt: hoursAgo(26.8),
      },
    ],
    diffs: [
      {
        id: 'diff_04', runId: 'run_04', createdAt: hoursAgo(26.9),
        files: [
          {
            path: 'src/middleware/auth.ts', additions: 148, deletions: 0,
            patch: '@@ -0,0 +1,3 @@\n+export function requireRole(role: Role) {\n+  // 统一权限校验中间件…\n+}',
          },
          {
            path: 'src/routes/orders.ts', additions: 12, deletions: 31,
            patch: '@@ -12,9 +12,4 @@\n-  if (!user.can(\'orders:write\')) throw new Forbidden()\n+  requireRole(\'orders:write\')(req, res, next)',
          },
        ],
      },
    ],
    tests: [
      {
        id: 'test_04', runId: 'run_04', passed: 15, failed: 3, skipped: 0,
        failures: [
          { name: 'admin/orders › 拒绝非 owner 更新', message: 'expected 403, received 200' },
          { name: 'admin/orders › 拒绝跨租户读取', message: 'expected 403, received 200' },
          { name: 'admin/billing › 仅 admin 可导出', message: 'expected 403, received 404' },
        ],
        createdAt: hoursAgo(26.7),
      },
    ],
  },
  task_05: {
    messages: [
      {
        id: 'msg_05_1', runId: 'run_05', role: 'user',
        content: '为仓库 README 补充本地部署与 Docker Compose 启动说明。',
        createdAt: hoursAgo(30),
      },
      {
        id: 'msg_05_2', runId: 'run_05', role: 'reviewer',
        content: '已补充「本地部署」与「Docker Compose」两节，命令已按 compose.yaml 实际服务名校对。',
        createdAt: hoursAgo(29.95), tokens: 150,
      },
    ],
    plan: {
      id: 'plan_05', runId: 'run_05', revision: 1,
      steps: [
        { id: 's1', index: 1, title: '读取 compose.yaml 与 .env.example', agent: 'executor', status: 'done', attempt: 1, toolCallIds: ['tc_05_1'] },
        { id: 's2', index: 2, title: '撰写 README 部署章节', agent: 'executor', status: 'done', attempt: 1, toolCallIds: [] },
      ],
    },
    toolCalls: [
      {
        id: 'tc_05_1', runId: 'run_05', server: 'filesystem', tool: 'read_file',
        args: { path: 'compose.yaml' }, resultSummary: '读取成功（64 行）',
        status: 'succeeded', risk: 'safe', durationMs: 180, createdAt: hoursAgo(30),
      },
    ],
    diffs: [
      {
        id: 'diff_05', runId: 'run_05', createdAt: hoursAgo(29.96),
        files: [
          {
            path: 'README.md', additions: 46, deletions: 2,
            patch: '@@ -38,3 +38,10 @@\n+## 本地部署\n+```bash\n+docker compose up -d\n+```\n+## 环境变量\n+参见 .env.example。',
          },
        ],
      },
    ],
    tests: [],
  },
}

export function historyForTask(taskId: string): TerminalHistory {
  return TERMINAL_HISTORY[taskId] ?? { messages: [], plan: null, toolCalls: [], diffs: [], tests: [] }
}

export function emptyPage<T>(items: T[]): Page<T> {
  return { items, total: items.length, page: 1, size: items.length }
}
