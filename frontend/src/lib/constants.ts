import type { AgentRole, TaskStatus } from '@/types/api'

/**
 * 状态 → 展示元数据（docs/03 §2.3 状态语言）。
 * tone 决定 StatusDot / StatusBadge 配色。
 */
export type StatusTone =
  | 'idle'
  | 'planning'
  | 'running'
  | 'reviewing'
  | 'waiting'
  | 'success'
  | 'failed'

interface StatusMeta {
  label: string
  tone: StatusTone
}

export const STATUS_META: Record<TaskStatus, StatusMeta> = {
  queued: { label: '排队中', tone: 'idle' },
  planning: { label: '规划中', tone: 'planning' },
  executing: { label: '执行中', tone: 'running' },
  reviewing: { label: '审查中', tone: 'reviewing' },
  waiting_approval: { label: '等待审批', tone: 'waiting' },
  completed: { label: '已完成', tone: 'success' },
  failed: { label: '失败', tone: 'failed' },
  cancelled: { label: '已取消', tone: 'idle' },
}

/** Agent 角色元数据（角色色见 docs/03 §2.4） */
export const AGENT_META: Record<AgentRole, { label: string; short: string; colorClass: string }> = {
  planner: { label: 'Planner', short: 'PL', colorClass: 'text-agent-planner bg-agent-planner' },
  executor: { label: 'Executor', short: 'EX', colorClass: 'text-agent-executor bg-agent-executor' },
  reviewer: { label: 'Reviewer', short: 'RV', colorClass: 'text-agent-reviewer bg-agent-reviewer' },
  replanner: { label: 'Replanner', short: 'RP', colorClass: 'text-agent-replanner bg-agent-replanner' },
  user: { label: '用户', short: 'U', colorClass: 'text-agent-user bg-agent-user' },
  system: { label: '系统', short: 'S', colorClass: 'text-foreground-muted bg-elevated' },
}

export const MODEL_META: Record<string, { label: string; chipClass: string }> = {
  'glm-5.3': { label: 'GLM-5.3', chipClass: 'border-primary/40 text-primary' },
  'glm-5.3-flash': { label: 'GLM-5.3-Flash', chipClass: 'border-accent/40 text-accent' },
  auto: { label: '自动路由', chipClass: 'border-border-strong text-foreground-secondary' },
}

export const modelLabel = (model: string): string =>
  MODEL_META[model]?.label ?? model

export const RISK_META: Record<string, { label: string; badgeClass: string }> = {
  safe: { label: 'safe', badgeClass: 'bg-hover text-foreground-muted' },
  gated: { label: 'gated', badgeClass: 'bg-warning-soft text-warning' },
  dangerous: { label: 'dangerous', badgeClass: 'bg-danger-soft text-danger' },
}
