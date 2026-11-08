import { ArrowDown, Unplug } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApprovalCard } from '@/components/agents/ApprovalCard'
import { DiffCard } from '@/components/agents/DiffCard'
import { TestResultCard } from '@/components/agents/TestResultCard'
import { ToolCallCard } from '@/components/agents/ToolCallCard'
import { MessageBubble } from './MessageBubble'
import { buildTimeline, useRunStore, type TimelineKind } from '../runStore'
import { useSearchParamsState } from '@/hooks/useSearchParamsState'
import { cn } from '@/lib/utils'

const FILTERS: { key: 'all' | TimelineKind; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'tool', label: '工具调用' },
  { key: 'diff', label: '代码' },
  { key: 'test', label: '测试' },
  { key: 'approval', label: '审批' },
]

/** 中栏：执行时间线（docs/05 §2 F-W4）— 事件按时间正序、类型筛选、自动跟随 + 新事件提示 */
export function EventTimeline() {
  const state = useRunStore((s) => s.state)
  const stream = useRunStore((s) => s.stream)
  const [filter, setFilter] = useSearchParamsState('filter', 'all')
  const activeFilter = (FILTERS.some((f) => f.key === filter) ? filter : 'all') as 'all' | TimelineKind

  const items = useMemo(() => buildTimeline(state, activeFilter), [state, activeFilter])
  const scrollRef = useRef<HTMLDivElement>(null)
  const nearBottomRef = useRef(true)
  const [newCount, setNewCount] = useState(0)
  const prevCountRef = useRef(0)

  const scrollToBottom = (smooth = true) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    setNewCount(0)
  }

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const count = items.length
    if (count > prevCountRef.current) {
      if (nearBottomRef.current) {
        el.scrollTop = el.scrollHeight
      } else {
        setNewCount((c) => c + (count - prevCountRef.current))
      }
    }
    prevCountRef.current = count
  }, [items.length])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (nearBottomRef.current) setNewCount(0)
  }

  return (
    <div className="relative flex min-h-0 flex-col rounded-xl border border-border bg-surface">
      {/* 筛选 chips + 连接状态 */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cn(
              'rounded-full px-2.5 py-1 text-2xs transition-colors',
              activeFilter === f.key
                ? 'bg-primary-soft font-medium text-primary'
                : 'text-foreground-secondary hover:bg-hover hover:text-foreground',
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-1.5 text-2xs text-foreground-muted">
          <i
            className={cn(
              'inline-block size-1.5 rounded-full',
              stream === 'live' && 'animate-pulse-soft bg-success',
              stream === 'connecting' && 'bg-foreground-muted',
              stream === 'down' && 'bg-danger',
              stream === 'idle' && 'bg-border-strong',
            )}
            aria-hidden="true"
          />
          {stream === 'live' ? '实时' : stream === 'connecting' ? '连接中' : stream === 'down' ? '已断开' : '未连接'}
        </span>
      </div>

      {stream === 'down' && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-3 py-1.5 text-2xs text-warning">
          <Unplug className="size-3.5" aria-hidden="true" />
          实时连接中断，正在自动重连并续传事件…
        </div>
      )}

      {/* 时间线 */}
      <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {items.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-xs leading-6 text-foreground-muted">
              <p>等待执行事件…</p>
              <p>计划、工具调用、代码变更与测试结果将按时间排列</p>
            </div>
          </div>
        )}
        {items.map((item) => {
          switch (item.kind) {
            case 'message':
              return item.message && <MessageBubble key={item.key} message={item.message} />
            case 'tool':
              return item.toolCall && <ToolCallCard key={item.key} call={item.toolCall} />
            case 'diff':
              return item.diff?.files[0] && <DiffCard key={item.key} file={item.diff.files[0]} />
            case 'test':
              return item.test && <TestResultCard key={item.key} result={item.test} />
            case 'approval':
              return item.approval && <ApprovalCard key={item.key} approval={item.approval} />
            default:
              return null
          }
        })}
      </div>

      {/* 回到底部（用户上滚时，docs/05 §2） */}
      {newCount > 0 && (
        <button
          type="button"
          onClick={() => scrollToBottom()}
          className="absolute bottom-16 left-1/2 z-10 -translate-x-1/2 rounded-full border border-border bg-elevated px-3 py-1.5 text-2xs text-foreground shadow-pop transition-colors hover:bg-hover"
        >
          <ArrowDown className="mr-1 inline size-3" aria-hidden="true" />
          {newCount} 条新事件
        </button>
      )}

      {/* 运行摘要（终态） */}
      {state.summary && state.runStatus && ['completed', 'failed', 'cancelled'].includes(state.runStatus) && (
        <div className="border-t border-border px-3 py-2 text-xs text-foreground-secondary">
          <span className={state.runStatus === 'completed' ? 'text-success' : state.runStatus === 'failed' ? 'text-danger' : 'text-foreground-muted'}>
            {state.runStatus === 'completed' ? '✓' : state.runStatus === 'failed' ? '✗' : '■'}
          </span>{' '}
          {state.summary}
        </div>
      )}
    </div>
  )
}
