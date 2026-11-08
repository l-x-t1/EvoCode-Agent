import type { StatusTone } from '@/lib/constants'
import { cn } from '@/lib/utils'

const toneClasses: Record<StatusTone, string> = {
  idle: 'bg-foreground-muted',
  planning: 'bg-agent-planner',
  running: 'bg-accent',
  reviewing: 'bg-info',
  waiting: 'bg-warning',
  success: 'bg-success',
  failed: 'bg-danger',
}

interface StatusDotProps {
  tone: StatusTone
  className?: string
}

/**
 * 统一状态点（docs/03 §5.2）。
 * running 为全站唯一允许的循环动画：2s 透明度脉冲。
 */
export function StatusDot({ tone, className }: StatusDotProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-2 shrink-0 rounded-full',
        toneClasses[tone],
        tone === 'running' && 'animate-pulse-soft',
        className,
      )}
    />
  )
}
