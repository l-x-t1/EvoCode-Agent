import type { ReactNode } from 'react'
import { MockBadge } from '@/components/common/MockBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface ChartCardProps {
  title: string
  /** 图例等头部右侧内容 */
  extra?: ReactNode
  mock?: boolean
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** 空态文案（无数据时） */
  emptyText?: string
  isEmpty?: boolean
  children: ReactNode
  className?: string
}

/** 图表容器：标题 + Mock 标注 + 三态（loading/empty/error）统一（docs/03 §5.2） */
export function ChartCard({
  title,
  extra,
  mock,
  loading,
  error,
  onRetry,
  emptyText = '暂无数据',
  isEmpty,
  children,
  className,
}: ChartCardProps) {
  return (
    <section className={cn('rounded-xl border border-border bg-surface p-4 shadow-card', className)}>
      <header className="mb-3 flex min-h-8 flex-wrap items-center gap-2">
        <h3 className="text-base font-medium text-foreground">{title}</h3>
        {mock && <MockBadge />}
        {extra && <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-foreground-secondary">{extra}</div>}
      </header>
      {loading ? (
        <Skeleton className="h-52 w-full rounded-lg" />
      ) : error ? (
        <button
          type="button"
          onClick={onRetry}
          className="flex h-52 w-full flex-col items-center justify-center gap-2 rounded-lg text-sm text-foreground-secondary transition-colors hover:text-foreground"
        >
          <span className="text-danger">加载失败</span>
          <span className="text-xs">点击重试</span>
        </button>
      ) : isEmpty ? (
        <div className="flex h-52 items-center justify-center text-sm text-foreground-muted">{emptyText}</div>
      ) : (
        children
      )}
    </section>
  )
}

/** 图例圆点 + 文案 */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <>
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          <i className="inline-block size-2 rounded-sm" style={{ background: it.color }} aria-hidden="true" />
          {it.label}
        </span>
      ))}
    </>
  )
}
