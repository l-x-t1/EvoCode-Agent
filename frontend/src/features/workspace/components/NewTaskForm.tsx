import { ArrowRight, History } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TimeAgo } from '@/components/common/TimeAgo'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useApi } from '@/hooks/useApi'
import { createTask, fetchTasks } from '../api'

/**
 * /workspace 空态（验收 M5）：新建入口 + 全部任务列表，
 * 使 Dashboard「查看全部」的跳转语义成立。
 */
export function NewTaskForm() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { data, loading } = useApi(fetchTasks, [])

  const submit = async () => {
    const t = title.trim()
    if (!t || submitting) return
    setSubmitting(true)
    try {
      const task = await createTask({ title: t })
      navigate(`/workspace/${task.id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 pt-2">
      <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
        <h2 className="text-base font-semibold text-foreground">新建研发任务</h2>
        <p className="mt-1 text-xs text-foreground-secondary">
          描述你的需求，Agent 将自主规划、调用工具并执行测试；危险操作会请求你的确认。
        </p>
        <textarea
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit()
          }}
          rows={4}
          autoFocus
          placeholder="例如：修复 user.test.ts 中失败的 2 个用例，跑通全部测试后推送分支…"
          className="mt-3 w-full resize-none rounded-lg border border-border bg-elevated px-3 py-2.5 text-sm text-foreground placeholder:text-foreground-muted focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-primary/60"
        />
        <div className="mt-3 flex items-center">
          <span className="text-2xs text-foreground-muted">Ctrl + Enter 提交</span>
          <Button className="ml-auto" disabled={!title.trim() || submitting} onClick={() => void submit()}>
            {submitting ? '创建中…' : '开始执行'}
            <ArrowRight aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-foreground-secondary">
          <History className="size-3.5" aria-hidden="true" />
          全部任务
        </h3>
        <div className="space-y-1">
          {loading && Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 w-full" />)}
          {data?.items.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => navigate(`/workspace/${t.id}`)}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-hover"
            >
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">{t.title}</span>
              <TimeAgo value={t.updatedAt} className="hidden shrink-0 sm:block" />
              <StatusBadge status={t.status} />
            </button>
          ))}
          {!loading && data?.items.length === 0 && (
            <p className="py-4 text-center text-xs text-foreground-muted">
              还没有任务。提交第一个研发需求后，这里会显示全部执行记录。
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
