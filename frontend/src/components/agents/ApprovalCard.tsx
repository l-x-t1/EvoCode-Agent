import { ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useId } from 'react'
import { cn } from '@/lib/utils'
import { request } from '@/api/client'
import { endpoints } from '@/api/endpoints'
import { toast } from 'sonner'
import type { Approval } from '@/types/api'

interface ApprovalCardProps {
  approval: Approval
  className?: string
}

/** 人工审批卡（docs/05 §2 F-W8）：危险操作 → 批准/拒绝，决策经 POST /approvals/:id 恢复执行流 */
export function ApprovalCard({ approval, className }: ApprovalCardProps) {
  const id = useId()
  const pending = approval.status === 'pending'

  const decide = async (decision: 'approved' | 'rejected') => {
    try {
      await request(endpoints.resolveApproval(approval.id), {
        method: 'POST',
        body: { decision },
      })
      toast.success(decision === 'approved' ? '已批准，执行流恢复' : '已拒绝，Agent 将修订计划')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '操作失败')
    }
  }

  return (
    <div
      role={pending ? 'alert' : undefined}
      className={cn(
        'rounded-xl border bg-warning-soft p-3',
        pending ? 'border-warning/50' : 'border-border opacity-80',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />
        <span className="text-sm font-medium text-warning">
          {pending ? '等待人工审批 · 危险操作' : approval.status === 'approved' ? '已批准' : approval.status === 'rejected' ? '已拒绝' : '已过期'}
        </span>
        <code className="ml-auto rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-2xs text-foreground">
          {approval.tool}
        </code>
      </div>
      <p className="mt-2 text-xs leading-5 text-foreground-secondary">{approval.summary}</p>
      {pending ? (
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" onClick={() => void decide('approved')}>
            批准
          </Button>
          <Button size="sm" variant="danger" onClick={() => void decide('rejected')}>
            拒绝
          </Button>
          <span className="ml-auto font-mono text-2xs text-foreground-muted" aria-live="polite">
            等待决策中
          </span>
        </div>
      ) : (
        <p className="mt-2 font-mono text-2xs text-foreground-muted">
          决策时间 {approval.resolvedAt ? new Date(approval.resolvedAt).toLocaleTimeString('zh-CN', { hour12: false }) : '—'}
        </p>
      )}
      <span id={id} className="sr-only">
        审批请求：{approval.summary}
      </span>
    </div>
  )
}
