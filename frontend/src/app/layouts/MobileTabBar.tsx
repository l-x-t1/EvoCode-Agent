import { BrainCircuit, Ellipsis, LayoutDashboard, Library, Sparkles, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

interface TabItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

const PRIMARY_TABS: TabItem[] = [
  { to: '/', label: '工作台', icon: LayoutDashboard, end: true },
  { to: '/workspace', label: '执行', icon: Sparkles },
  { to: '/skills', label: 'Skills', icon: Library },
  { to: '/context', label: '上下文', icon: BrainCircuit },
]

const MORE_LINKS = [
  { to: '/workflow', label: 'Workflow Center' },
  { to: '/evaluation', label: 'Evaluation Center' },
  { to: '/settings/models', label: 'Settings' },
]

/** 移动端底部 TabBar（<lg 显示，docs/02 §5）：4 主项 + 「更多」收纳 */
export function MobileTabBar() {
  const [moreOpen, setMoreOpen] = useState(false)

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
      aria-label="移动端主导航"
    >
      {moreOpen && (
        <div className="absolute bottom-full inset-x-0 border-t border-border bg-elevated p-2 shadow-pop animate-fade-in">
          {MORE_LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              onClick={() => setMoreOpen(false)}
              className={({ isActive }) =>
                cn(
                  'block rounded-lg px-4 py-2.5 text-sm text-foreground-secondary',
                  isActive && 'bg-primary-soft text-foreground',
                )
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>
      )}
      <div className="grid grid-cols-5">
        {PRIMARY_TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                'flex flex-col items-center gap-0.5 py-2 text-2xs text-foreground-muted',
                isActive && 'text-primary',
              )
            }
          >
            <tab.icon className="size-5" aria-hidden="true" />
            {tab.label}
          </NavLink>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen((v) => !v)}
          aria-expanded={moreOpen}
          className={cn(
            'flex flex-col items-center gap-0.5 py-2 text-2xs text-foreground-muted',
            moreOpen && 'text-primary',
          )}
        >
          <Ellipsis className="size-5" aria-hidden="true" />
          更多
        </button>
      </div>
    </nav>
  )
}
