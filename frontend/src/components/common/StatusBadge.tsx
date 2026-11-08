import { STATUS_META } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type { TaskStatus } from '@/types/api'
import { StatusDot } from './StatusDot'

const badgeToneClasses: Record<string, string> = {
  idle: 'bg-hover text-foreground-secondary',
  planning: 'bg-primary-soft text-primary',
  running: 'bg-accent-soft text-accent',
  reviewing: 'bg-info-soft text-info',
  waiting: 'bg-warning-soft text-warning',
  success: 'bg-success-soft text-success',
  failed: 'bg-danger-soft text-danger',
}

interface StatusBadgeProps {
  status: TaskStatus
  className?: string
  /** 不带圆点，仅文字 */
  textOnly?: boolean
}

/** 统一状态徽标：StatusDot + 中文标签（状态即信息，docs/03 §1） */
export function StatusBadge({ status, className, textOnly = false }: StatusBadgeProps) {
  const meta = STATUS_META[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-2xs font-medium',
        badgeToneClasses[meta.tone],
        className,
      )}
    >
      {!textOnly && <StatusDot tone={meta.tone} className="size-1.5" />}
      {meta.label}
    </span>
  )
}
