import { Link } from 'react-router-dom'
import { CONTEXT_SEGMENT_COLORS } from '@/components/charts/chartTheme'

/** 未识别段的兜底中性色 */
const CHART_NEUTRAL_FALLBACK = '#64748b'
import { cn } from '@/lib/utils'
import type { ContextSession } from '@/types/api'

/** 分段中文标签 */
const SEGMENT_LABEL: Record<string, string> = {
  system: '系统提示',
  skill: 'Skill',
  memory: '记忆',
  history: '历史',
  working: '工作集',
  compressed: '已压缩',
}

interface ContextGaugeProps {
  session: ContextSession
  /** 迷你模式（Workspace 右栏） */
  mini?: boolean
  className?: string
}

/** 上下文用量仪表（docs/05 §2 F-W10 / §4 F-C1）：分段环形 + 图例 */
export function ContextGauge({ session, mini = false, className }: ContextGaugeProps) {
  const pct = Math.min(session.usedTokens / session.windowTokens, 1)
  const R = 42
  const C = 2 * Math.PI * R
  let offset = 0
  const arcs = session.segments.map((seg) => {
    const frac = session.usedTokens > 0 ? seg.tokens / session.usedTokens : 0
    const arc = { ...seg, frac, dash: frac * C, offset }
    offset += arc.dash
    return arc
  })

  const gauge = (
    <div className={cn('flex items-center gap-4', className)}>
      <svg
        width={mini ? 72 : 120}
        height={mini ? 72 : 120}
        viewBox="0 0 100 100"
        role="img"
        aria-label={`上下文已用 ${Math.round(pct * 100)}%`}
      >
        <circle cx="50" cy="50" r={R} fill="none" stroke="hsl(226 14% 17%)" strokeWidth="10" />
        <g transform="rotate(-90 50 50)">
          {arcs.map((a) =>
            a.frac > 0.001 ? (
              <circle
                key={a.key}
                cx="50"
                cy="50"
                r={R}
                fill="none"
                stroke={CONTEXT_SEGMENT_COLORS[a.key] ?? CHART_NEUTRAL_FALLBACK}
                strokeWidth="10"
                strokeDasharray={`${a.dash} ${C - a.dash}`}
                strokeDashoffset={-a.offset}
              />
            ) : null,
          )}
        </g>
        <text
          x="50"
          y="48"
          textAnchor="middle"
          fontSize="15"
          fontWeight="600"
          fill="hsl(220 25% 95%)"
          fontFamily="JetBrains Mono, monospace"
        >
          {Math.round(pct * 100)}%
        </text>
        <text x="50" y="62" textAnchor="middle" fontSize="8" fill="hsl(220 10% 46%)">
          {Math.round(session.usedTokens / 1000)}K
        </text>
      </svg>
      {!mini && (
        <ul className="min-w-0 flex-1 space-y-1">
          {arcs.map((a) => (
            <li key={a.key} className="flex items-center gap-2 text-xs text-foreground-secondary">
              <i
                className="inline-block size-2 shrink-0 rounded-sm"
                style={{ background: CONTEXT_SEGMENT_COLORS[a.key] ?? CHART_NEUTRAL_FALLBACK }}
                aria-hidden="true"
              />
              {SEGMENT_LABEL[a.key] ?? a.key}
              <span className="ml-auto font-mono text-2xs text-foreground-muted">
                {Math.round(a.tokens / 1000)}K
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )

  if (mini) {
    return (
      <Link
        to={`/context/${session.id}`}
        title="查看上下文详情（Context Center）"
        className="block rounded-xl border border-border bg-surface p-3 transition-colors hover:border-border-strong"
      >
        {gauge}
      </Link>
    )
  }
  return gauge
}
