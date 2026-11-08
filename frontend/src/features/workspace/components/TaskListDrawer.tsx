import { useNavigate } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TimeAgo } from '@/components/common/TimeAgo'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useApi } from '@/hooks/useApi'
import { fetchTasks } from '../api'

interface TaskListDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentTaskId?: string
}

/** 任务列表抽屉（docs/05 §2 F-W12）：快速切换任务 */
export function TaskListDrawer({ open, onOpenChange, currentTaskId }: TaskListDrawerProps) {
  const navigate = useNavigate()
  const { data, loading } = useApi(fetchTasks, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogTitle>任务列表</DialogTitle>
        <div className="mt-3 max-h-96 space-y-1 overflow-y-auto pr-1">
          {loading && Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
          {data?.items.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                onOpenChange(false)
                navigate(`/workspace/${t.id}`)
              }}
              className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors hover:bg-hover ${
                t.id === currentTaskId ? 'border-primary/40 bg-primary-soft' : 'border-transparent bg-surface'
              }`}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-foreground">{t.title}</p>
                <TimeAgo value={t.updatedAt} className="mt-0.5 block" />
              </div>
              <StatusBadge status={t.status} />
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
