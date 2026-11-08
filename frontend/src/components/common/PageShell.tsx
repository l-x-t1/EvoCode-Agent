import type { ReactNode } from 'react'
import { MockBadge } from './MockBadge'
import { cn } from '@/lib/utils'

interface PageShellProps {
  title: string
  description?: string
  /** 页头右侧动作区（范围切换、主按钮等） */
  actions?: ReactNode
  /** 页面数据来自 Mock 时在页头标注一次（docs/05 §8） */
  mock?: boolean
  children?: ReactNode
  className?: string
}

/** 统一页面壳：页头（Title-L）+ 内容区（流式宽度 + 24px 内边距，docs/03 §7） */
export function PageShell({ title, description, actions, mock, children, className }: PageShellProps) {
  return (
    <div className={cn('mx-auto w-full max-w-6xl space-y-6', className)}>
      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
          {description && <p className="mt-0.5 text-sm text-foreground-secondary">{description}</p>}
        </div>
        {mock && <MockBadge />}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </div>
  )
}
