import type {
  DashboardSummary,
  DashboardTrends,
  SkillEvent,
} from '@/types/api'

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()

export const SUMMARY_FIXTURE: DashboardSummary = {
  tasksTotal: 128,
  tasksToday: 12,
  tasksRunning: 3,
  tokensTotal: 4_233_600,
  tokensToday: 318_400,
  skillCount: 24,
  skillEvolutions: 7,
  successRate: 0.87,
}

/** 确定性伪随机（同会话内图表稳定） */
function seeded(i: number, salt = 1): number {
  const x = Math.sin(i * 127.1 * salt + 311.7) * 43758.5453
  return x - Math.floor(x)
}

function lastNDates(n: number): string[] {
  const out: string[] = []
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86_400_000)
    out.push(`${d.getMonth() + 1}/${d.getDate()}`)
  }
  return out
}

/** 生成 30 天趋势，7d/14d 由 handler 截取 */
export function buildTrends(): DashboardTrends {
  const dates = lastNDates(30)
  const taskTrend = dates.map((date, i) => {
    const created = 5 + Math.round(seeded(i, 1) * 8) + (i > 20 ? 2 : 0)
    const failed = Math.round(seeded(i, 2) * 2)
    return { date, created, succeeded: Math.max(created - failed, 0), failed }
  })
  const tokenTrend = dates.map((date, i) => ({
    date,
    glm53: 90 + Math.round(seeded(i, 3) * 120),
    flash: 30 + Math.round(seeded(i, 4) * 45),
  }))
  return { range: '30d', taskTrend, tokenTrend }
}

export const AGENT_STATUS_FIXTURE = {
  total: 8,
  items: [
    { name: '运行中', value: 3 },
    { name: '等待审批', value: 1 },
    { name: '空闲', value: 4 },
  ],
}

export const SKILL_EVENTS_FIXTURE: SkillEvent[] = [
  {
    id: 'skev_01',
    skillId: 'skill_unittest_fix',
    type: 'proposed',
    message: '候选「单测修复」v3.3 待审核 · 回归评测 +9.2%',
    createdAt: minsAgo(12),
  },
  {
    id: 'skev_02',
    skillId: 'skill_code_review',
    type: 'rolled_back',
    message: '「代码审查」回滚至 v1.3（审查通过率下降）',
    createdAt: minsAgo(125),
  },
  {
    id: 'skev_03',
    skillId: 'skill_flaky_debug',
    type: 'approved',
    message: '「flaky 用例排查」进化 #7 已合入',
    createdAt: minsAgo(1500),
  },
  {
    id: 'skev_04',
    skillId: 'skill_docs_gen',
    type: 'created',
    message: '新增候选「文档生成」v1.0（来自任务 #96）',
    createdAt: minsAgo(2900),
  },
  {
    id: 'skev_05',
    skillId: 'skill_refactor_guard',
    type: 'approved',
    message: '「重构守护」进化 #12 已合入',
    createdAt: minsAgo(4300),
  },
]
