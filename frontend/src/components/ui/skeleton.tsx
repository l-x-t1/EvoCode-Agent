import { forwardRef, type HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** 骨架屏：低对比脉冲占位（loading 三态之一，docs/05 §8） */
export const Skeleton = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('animate-pulse rounded-lg bg-hover', className)} {...props} />
  ),
)
Skeleton.displayName = 'Skeleton'
