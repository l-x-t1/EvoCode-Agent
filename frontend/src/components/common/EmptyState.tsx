import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  /** 说明「为什么是空的」+「下一步做什么」（docs/05 §8） */
  description?: string
  action?: ReactNode
  className?: string
}

/** 空态：禁止只写「无数据」 */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-12 text-center',
        className,
      )}
    >
      {Icon && (
        <div className="mb-1 flex size-10 items-center justify-center rounded-xl bg-hover text-foreground-muted">
          <Icon className="size-5" aria-hidden="true" />
        </div>
      )}
      <p className="text-base font-medium text-foreground">{title}</p>
      {description && <p className="max-w-md text-sm text-foreground-secondary">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
