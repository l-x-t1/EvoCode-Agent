import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** 页面级加载骨架：页头 + KPI 行 + 图表区（各页面可覆盖 children） */
export function PageSkeleton({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('space-y-6', className)} aria-busy="true" aria-label="页面加载中">
      <div className="flex items-center gap-3">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="ml-auto h-8 w-24" />
      </div>
      {children ?? (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-64 rounded-xl lg:col-span-2" />
            <Skeleton className="h-64 rounded-xl" />
          </div>
        </>
      )}
    </div>
  )
}
