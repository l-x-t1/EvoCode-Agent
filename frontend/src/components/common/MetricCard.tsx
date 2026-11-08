import { Link } from 'react-router-dom'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { Sparkline } from './Sparkline'

interface MetricCardProps {
  label: string
  value: string
  /** 变化标注，如 "+12 今日" */
  delta?: string
  deltaTone?: 'up' | 'down' | 'neutral'
  sub?: string
  spark?: number[]
  sparkColor?: string
  loading?: boolean
  to?: string
  className?: string
}

/** KPI 指标卡（docs/03 §5.2）：label + 大数字 + delta + 可选 sparkline */
export function MetricCard({
  label,
  value,
  delta,
  deltaTone = 'neutral',
  sub,
  spark,
  sparkColor,
  loading,
  to,
  className,
}: MetricCardProps) {
  const inner = (
    <>
      <p className="text-xs text-foreground-muted">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-20" />
      ) : (
        <p className="mt-1.5 font-mono text-[26px] font-semibold leading-8 text-foreground">{value}</p>
      )}
      {(delta || sub) && !loading && (
        <div className="mt-1.5 flex items-center gap-2 text-xs text-foreground-secondary">
          {delta && (
            <span
              className={cn(
                'rounded px-1.5 py-0.5 text-2xs font-medium',
                deltaTone === 'up' && 'bg-success-soft text-success',
                deltaTone === 'down' && 'bg-danger-soft text-danger',
                deltaTone === 'neutral' && 'bg-hover text-foreground-secondary',
              )}
            >
              {delta}
            </span>
          )}
          {sub && <span className="truncate">{sub}</span>}
        </div>
      )}
      {spark && spark.length > 1 && !loading && (
        <Sparkline data={spark} color={sparkColor} className="mt-2" />
      )}
    </>
  )

  const cls = cn('rounded-xl border border-border bg-surface p-4 shadow-card', className)
  if (to) {
    return (
      <Link to={to} className={cn(cls, 'block transition-colors hover:border-border-strong')}>
        {inner}
      </Link>
    )
  }
  return <div className={cls}>{inner}</div>
}
