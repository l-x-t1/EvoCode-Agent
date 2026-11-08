import { FolderOutput, ShieldAlert } from 'lucide-react'
import { ContextGauge } from '@/components/agents/ContextGauge'
import { PlanTree } from '@/components/agents/PlanTree'
import { EmptyState } from '@/components/common/EmptyState'
import type { CodeDiff, ContextSession, Plan } from '@/types/api'

interface PlanPanelProps {
  plan: Plan | null
  context: ContextSession | null
  diffs: CodeDiff[]
  pendingApprovals: number
  onGotoApprovals: () => void
}

/** 右栏：计划 + 上下文迷你仪表 + 产物（docs/05 §2 F-W9~F-W11） */
export function PlanPanel({ plan, context, diffs, pendingApprovals, onGotoApprovals }: PlanPanelProps) {
  const files = diffs.flatMap((d) => d.files)

  return (
    <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5">
      {/* 待审批提醒条 */}
      {pendingApprovals > 0 && (
        <button
          type="button"
          onClick={onGotoApprovals}
          className="flex shrink-0 items-center gap-2 rounded-xl border border-warning/50 bg-warning-soft px-3 py-2 text-left text-xs text-warning transition-colors hover:bg-warning/20"
        >
          <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
          {pendingApprovals} 个操作等待审批，点击在时间线中处理
        </button>
      )}

      {/* 计划树 */}
      <section className="shrink-0 rounded-xl border border-border bg-surface p-3">
        <h3 className="mb-2 text-xs font-medium text-foreground-secondary">执行计划</h3>
        {plan ? (
          <PlanTree plan={plan} />
        ) : (
          <p className="py-3 text-center text-xs text-foreground-muted">等待 Planner 产出计划…</p>
        )}
      </section>

      {/* 上下文迷你仪表 */}
      {context && (
        <section className="shrink-0">
          <ContextGauge session={context} mini />
        </section>
      )}

      {/* 产物：变更文件 */}
      <section className="shrink-0 rounded-xl border border-border bg-surface p-3">
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-foreground-secondary">
          <FolderOutput className="size-3.5" aria-hidden="true" />
          变更文件
        </h3>
        {files.length === 0 ? (
          <p className="py-2 text-center text-xs text-foreground-muted">暂无代码变更</p>
        ) : (
          <ul className="space-y-1">
            {files.map((f, i) => (
              <li key={`${f.path}_${i}`} className="flex items-center gap-2 text-xs">
                <code className="min-w-0 truncate font-mono text-foreground-secondary" title={f.path}>
                  {f.path}
                </code>
                <span className="ml-auto shrink-0 font-mono text-2xs">
                  <span className="text-success">+{f.additions}</span>{' '}
                  <span className="text-danger">−{f.deletions}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {plan === null && context === null && files.length === 0 && (
        <EmptyState
          title="等待执行开始"
          description="连接事件流后，这里将展示执行计划、上下文用量与变更产物。"
          className="py-8"
        />
      )}
    </div>
  )
}
