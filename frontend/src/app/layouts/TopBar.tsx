import { Bell, Plus, Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusDot } from '@/components/common/StatusDot'
import { Button } from '@/components/ui/button'
import { useConnectionStore } from '@/stores/connectionStore'

/**
 * 顶栏（h-14）：全局搜索（⌘K，P2 接 SearchCommand）+ 运行状态 + 通知 + 新建任务。
 * 通知中心未实现（验收 M6）：不放虚构未读数，点击给出诚实反馈。
 */
export function TopBar() {
  const { apiHealthy } = useConnectionStore()

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-5">
      {/* 全局搜索（占位，P1 实现 SearchCommand） */}
      <button
        type="button"
        className="flex h-8 w-full max-w-[360px] items-center gap-2 rounded-lg border border-border bg-surface px-2.5 text-sm text-foreground-muted transition-colors hover:border-border-strong"
        aria-label="搜索任务与 Skill（快捷键 Ctrl K）"
      >
        <Search className="size-4" aria-hidden="true" />
        <span className="hidden sm:inline">搜索任务、Skill…</span>
        <kbd className="ml-auto hidden rounded border border-border-strong bg-elevated px-1.5 py-0.5 font-mono text-2xs text-foreground-muted sm:inline">
          ⌘K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-4">
        <span className="hidden items-center gap-2 text-sm text-foreground-secondary md:flex">
          <StatusDot tone={apiHealthy ? 'success' : 'failed'} />
          {apiHealthy ? '系统正常' : '系统异常'}
        </span>
        <button
          type="button"
          className="flex items-center rounded-lg p-1.5 text-foreground-secondary transition-colors hover:bg-hover hover:text-foreground"
          aria-label="通知中心（规划中）"
          onClick={() => toast.info('通知中心将在后续阶段提供')}
        >
          <Bell className="size-[18px]" aria-hidden="true" />
        </button>
        <Button asChild size="sm">
          <Link to="/workspace">
            <Plus aria-hidden="true" />
            新建任务
          </Link>
        </Button>
      </div>
    </header>
  )
}
