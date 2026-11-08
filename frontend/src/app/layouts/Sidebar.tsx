import { PanelLeftClose, PanelLeftOpen, Sparkles } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { StatusDot } from '@/components/common/StatusDot'
import { NAV_GROUPS } from '@/lib/nav'
import { cn } from '@/lib/utils'
import { useConnectionStore } from '@/stores/connectionStore'
import { useUiStore } from '@/stores/uiStore'

/** 侧边栏：232px ↔ 折叠 64px；<lg 隐藏由 MobileTabBar 接管（docs/02 §1） */
export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggle = useUiStore((s) => s.toggleSidebar)
  const { apiMode, apiHealthy } = useConnectionStore()

  return (
    <aside
      className={cn(
        'hidden h-full shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 lg:flex',
        collapsed ? 'w-16' : 'w-[232px]',
      )}
    >
      {/* Logo */}
      <div className={cn('flex items-center gap-2.5 px-4 pb-4 pt-5', collapsed && 'justify-center px-0')}>
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="size-4" aria-hidden="true" />
        </span>
        {!collapsed && <span className="text-base font-semibold tracking-wide">EvoCode Agent</span>}
      </div>

      {/* 导航分组 */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-2" aria-label="主导航">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <div className="px-2 pb-1 pt-4 text-2xs font-medium uppercase tracking-widest text-foreground-muted">
                {group.label}
              </div>
            )}
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-foreground-secondary transition-colors',
                    'hover:bg-hover hover:text-foreground',
                    isActive &&
                      'bg-primary-soft font-medium text-foreground shadow-[inset_2px_0_0_0_hsl(var(--primary))]',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <item.icon
                      className={cn('size-4 shrink-0', isActive ? 'text-primary' : 'text-foreground-muted')}
                      aria-hidden="true"
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* 底部：连接状态 + API 模式 + 折叠 */}
      <div className={cn('space-y-2 border-t border-border p-3', collapsed && 'flex flex-col items-center')}>
        <div className={cn('flex items-center gap-2 text-xs text-foreground-secondary', collapsed && 'hidden')}>
          <StatusDot tone={apiHealthy ? 'success' : 'failed'} />
          <span>{apiHealthy ? 'API 已连接' : 'API 不可用'}</span>
        </div>
        {collapsed && <StatusDot tone={apiHealthy ? 'success' : 'failed'} />}
        {!collapsed && (
          <span className="inline-flex items-center rounded-md border border-dashed border-border-strong px-2 py-0.5 text-2xs text-foreground-muted">
            {apiMode === 'mock' ? 'MOCK 模式' : 'LIVE 模式'}
          </span>
        )}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
          className={cn(
            'flex w-full items-center justify-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-hover hover:text-foreground',
            collapsed && 'w-9',
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" aria-hidden="true" />
          ) : (
            <>
              <PanelLeftClose className="size-4" aria-hidden="true" />
              折叠
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
