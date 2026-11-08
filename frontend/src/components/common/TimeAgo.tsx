import { timeAgo } from '@/lib/format'
import { cn } from '@/lib/utils'

interface TimeAgoProps {
  /** ISO 8601 UTC 字符串（docs/06 §1 时间约定） */
  value: string | Date
  className?: string
}

/** 相对时间展示，title 提供绝对时间 */
export function TimeAgo({ value, className }: TimeAgoProps) {
  const abs = typeof value === 'string' ? new Date(value) : value
  return (
    <time
      dateTime={abs.toISOString()}
      title={abs.toLocaleString('zh-CN', { hour12: false })}
      className={cn('text-2xs text-foreground-muted', className)}
    >
      {timeAgo(value)}
    </time>
  )
}
