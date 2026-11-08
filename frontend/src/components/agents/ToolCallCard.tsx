import { ChevronDown, ChevronRight, Clock } from 'lucide-react'
import { useState } from 'react'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils'
import { formatDuration } from '@/lib/format'
import { RISK_META } from '@/lib/constants'
import type { ToolCall } from '@/types/api'

const CALL_TONE = {
  running: 'running',
  succeeded: 'success',
  failed: 'failed',
  cancelled: 'idle',
} as const

/** 工具调用卡（docs/05 §2 F-W5）：状态 + 工具名 + server + 风险 + 可展开参数/结果 */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(call.status === 'failed')
  const risk = RISK_META[call.risk]
  const failed = call.status === 'failed'

  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border bg-surface',
        failed ? 'border-danger/40' : call.risk === 'dangerous' ? 'border-warning/40' : 'border-border',
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-hover"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="size-3.5 text-foreground-muted" aria-hidden="true" />
        ) : (
          <ChevronRight className="size-3.5 text-foreground-muted" aria-hidden="true" />
        )}
        <StatusDot tone={CALL_TONE[call.status]} />
        <code className="font-mono text-xs font-medium text-foreground">{call.tool}</code>
        <span className="rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-2xs text-foreground-secondary">
          {call.server}
        </span>
        <span className={cn('rounded px-1.5 py-0.5 text-2xs', risk.badgeClass)}>{risk.label}</span>
        {call.durationMs !== undefined && (
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-2xs text-foreground-muted">
            <Clock className="size-3" aria-hidden="true" />
            {formatDuration(call.durationMs)}
          </span>
        )}
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2.5">
          <pre className="overflow-x-auto rounded-lg border border-border bg-background p-2.5 font-mono text-2xs leading-5 text-foreground-secondary">
            {JSON.stringify(call.args, null, 2)}
          </pre>
          {call.resultSummary && (
            <p className="text-xs text-foreground-secondary">
              <span className="text-foreground-muted">结果：</span>
              {call.resultSummary}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
