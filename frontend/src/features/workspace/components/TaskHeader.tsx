import { GitBranch, List, Square, Workflow } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { modelLabel } from '@/lib/constants'
import type { Task } from '@/types/api'

interface TaskHeaderProps {
  task: Task
  onCancel: () => void
  onOpenList: () => void
}

const ACTIVE = ['queued', 'planning', 'executing', 'reviewing', 'waiting_approval']

/** 任务信息头（docs/05 §2 F-W1）：状态 + 模型 + Skill + 动作 */
export function TaskHeader({ task, onCancel, onOpenList }: TaskHeaderProps) {
  const active = ACTIVE.includes(task.status)

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <StatusBadge status={task.status} />
      <h1 className="min-w-0 truncate text-lg font-semibold text-foreground" title={task.title}>
        {task.title}
      </h1>
      <span className="rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-2xs text-foreground-secondary">
        {modelLabel(task.model)}
      </span>
      {task.repo && (
        <span className="hidden items-center gap-1 font-mono text-2xs text-foreground-muted sm:inline-flex">
          <GitBranch className="size-3" aria-hidden="true" />
          {task.repo}
        </span>
      )}
      {task.skillIds.length > 0 && (
        <Link
          to="/skills"
          className="rounded-full bg-primary-soft px-2 py-0.5 text-2xs text-primary transition-colors hover:bg-primary/20"
          title="查看所用 Skill"
        >
          使用 {task.skillIds.length} 个 Skill
        </Link>
      )}

      <div className="ml-auto flex items-center gap-1.5">
        {task.latestRunId && (
          <Button asChild variant="ghost" size="sm">
            <Link to={`/workflow/${task.latestRunId}`} title="在 Workflow Center 查看执行图">
              <Workflow aria-hidden="true" />
              <span className="hidden md:inline">执行图</span>
            </Link>
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onOpenList} aria-label="任务列表">
          <List aria-hidden="true" />
          <span className="hidden md:inline">任务列表</span>
        </Button>
        {active && (
          <Button variant="outline" size="sm" onClick={onCancel}>
            <Square aria-hidden="true" />
            <span className="hidden md:inline">取消任务</span>
          </Button>
        )}
      </div>
    </header>
  )
}
