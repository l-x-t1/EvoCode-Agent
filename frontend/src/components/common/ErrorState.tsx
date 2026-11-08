import { TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { isApiError } from '@/api/error'

interface ErrorStateProps {
  title?: string
  error?: unknown
  onRetry?: () => void
  /** 自定义动作区（优先于 onRetry 的默认重试按钮） */
  action?: ReactNode
  className?: string
}

/** 错误态：统一文案 + 重试按钮 */
export function ErrorState({ title = '加载失败', error, onRetry, action, className }: ErrorStateProps) {
  const message =
    error instanceof Error ? (isApiError(error) ? error.message : undefined) : undefined
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-12 text-center',
        className,
      )}
    >
      <div className="mb-1 flex size-10 items-center justify-center rounded-xl bg-danger-soft text-danger">
        <TriangleAlert className="size-5" aria-hidden="true" />
      </div>
      <p className="text-base font-medium text-foreground">{title}</p>
      {message && <p className="max-w-md text-sm text-foreground-secondary">{message}</p>}
      {action ? (
        <div className="mt-3">{action}</div>
      ) : (
        onRetry && (
          <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
            重试
          </Button>
        )
      )}
    </div>
  )
}
