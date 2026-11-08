import { Check, Circle, Play, RefreshCw, X, GitBranch } from 'lucide-react'
import { AgentAvatar } from './AgentAvatar'
import { cn } from '@/lib/utils'
import type { Plan } from '@/types/api'

const STEP_ICON = {
  pending: { icon: Circle, cls: 'border border-border-strong text-foreground-muted' },
  running: { icon: Play, cls: 'bg-accent-soft text-accent' },
  done: { icon: Check, cls: 'bg-success-soft text-success' },
  failed: { icon: X, cls: 'bg-danger-soft text-danger' },
  skipped: { icon: Circle, cls: 'border border-border text-foreground-muted' },
  replanned: { icon: GitBranch, cls: 'bg-info-soft text-info' },
} as const

/** 计划树（docs/05 §2 F-W9）：步骤状态 + 执行 Agent + 重规划标记 */
export function PlanTree({ plan }: { plan: Plan }) {
  return (
    <ol className="space-y-0.5" aria-label={`任务计划（第 ${plan.revision} 版）`}>
      {plan.steps.map((step) => {
        const meta = STEP_ICON[step.status]
        const Icon = meta.icon
        return (
          <li
            key={step.id}
            className={cn(
              'flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors',
              step.status === 'running' && 'bg-accent-soft/50',
            )}
          >
            <span className={cn('flex size-5 shrink-0 items-center justify-center rounded-full', meta.cls)}>
              <Icon
                className={cn('size-3', step.status === 'running' && 'animate-pulse-soft')}
                aria-hidden="true"
              />
            </span>
            <div className="min-w-0 flex-1">
              <p
                className={cn(
                  'truncate text-xs',
                  step.status === 'done' && 'text-foreground-muted',
                  step.status === 'pending' && 'text-foreground-secondary',
                  (step.status === 'running' || step.status === 'failed') && 'text-foreground',
                )}
              >
                {step.index}. {step.title}
              </p>
            </div>
            {step.attempt > 1 && (
              <span className="rounded bg-hover px-1.5 py-0.5 text-2xs text-foreground-muted">
                重试×{step.attempt - 1}
              </span>
            )}
            <AgentAvatar role={step.agent} size="sm" />
          </li>
        )
      })}
      {plan.revision > 1 && (
        <li className="flex items-center gap-2 px-2 pt-1.5 text-2xs text-info">
          <RefreshCw className="size-3" aria-hidden="true" />
          计划已重规划至第 {plan.revision} 版
        </li>
      )}
    </ol>
  )
}
