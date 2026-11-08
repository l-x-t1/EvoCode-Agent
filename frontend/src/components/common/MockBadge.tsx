import { FlaskConical } from 'lucide-react'
import { cn } from '@/lib/utils'

interface MockBadgeProps {
  className?: string
  /** 无 tooltip 版本（页面级只标一次时可关闭悬浮提示） */
  plain?: boolean
}

/**
 * 「模拟数据」标注（docs/05 §8 · docs/04 §5）。
 * 规则：所有由 Mock 驱动的区块必须挂此角标；接入真实 API 后随开关消失。
 */
export function MockBadge({ className, plain = false }: MockBadgeProps) {
  return (
    <span
      title={plain ? undefined : '当前展示为模拟数据（VITE_API_MODE=mock），接入后端后自动消失'}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-dashed border-border-strong px-2 py-0.5 text-2xs text-foreground-muted',
        className,
      )}
    >
      <FlaskConical className="size-3" aria-hidden="true" />
      模拟数据
    </span>
  )
}
