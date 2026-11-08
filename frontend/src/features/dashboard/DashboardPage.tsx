import {
  CircleAlert,
  CheckCircle2,
  Plus,
  RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ChartCard, ChartLegend } from '@/components/charts/ChartCard'
import { DonutChart, DonutLegend } from '@/components/charts/DonutChart'
import { StackedBar } from '@/components/charts/StackedBar'
import { TrendArea } from '@/components/charts/TrendArea'
import { CHART_SERIES_COLORS, DONUT_IDLE_COLOR } from '@/components/charts/chartTheme'
import { PageShell } from '@/components/common/PageShell'
import { StatusBadge } from '@/components/common/StatusBadge'
import { StatusDot } from '@/components/common/StatusDot'
import { TimeAgo } from '@/components/common/TimeAgo'
import { MetricCard } from '@/components/common/MetricCard'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDuration, formatTokens } from '@/lib/format'
import { modelLabel } from '@/lib/constants'
import { useApi } from '@/hooks/useApi'
import { useSearchParamsState } from '@/hooks/useSearchParamsState'
import { fetchTasks } from '@/features/workspace/api'
import {
  fetchAgentStatus,
  fetchSkillEvents,
  fetchSummary,
  fetchSystemHealth,
  fetchTrends,
} from './api'
import type { DashboardTrends, SkillEvent } from '@/types/api'

const EVENT_ICON = {
  proposed: { icon: CircleAlert, cls: 'text-warning' },
  approved: { icon: CheckCircle2, cls: 'text-success' },
  rejected: { icon: CircleAlert, cls: 'text-danger' },
  rolled_back: { icon: RotateCcw, cls: 'text-foreground-muted' },
  created: { icon: Plus, cls: 'text-primary' },
} as const

export default function DashboardPage() {
  const [range, setRange] = useSearchParamsState('range', '14d')
  const trendRange = (['7d', '14d', '30d'].includes(range) ? range : '14d') as '7d' | '14d' | '30d'

  const summary = useApi(fetchSummary, [])
  const trends = useApi<DashboardTrends>(() => fetchTrends(trendRange), [trendRange])
  const agentStatus = useApi(fetchAgentStatus, [])
  const skillEvents = useApi(fetchSkillEvents, [])
  const tasks = useApi(fetchTasks, [])
  const health = useApi(fetchSystemHealth, [])

  const recent = tasks.data?.items.slice(0, 6) ?? []

  return (
    <PageShell
      title="Dashboard"
      description="Agent 运行状态、任务与 Token 消耗总览"
      mock
      actions={
        <div className="flex rounded-lg border border-border bg-surface p-0.5" role="tablist" aria-label="时间范围">
          {(['7d', '14d', '30d'] as const).map((r) => (
            <button
              key={r}
              type="button"
              role="tab"
              aria-selected={trendRange === r}
              onClick={() => setRange(r)}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                trendRange === r
                  ? 'bg-elevated font-medium text-foreground'
                  : 'text-foreground-secondary hover:text-foreground'
              }`}
            >
              {r === '7d' ? '7 天' : r === '14d' ? '14 天' : '30 天'}
            </button>
          ))}
        </div>
      }
    >
      {/* KPI 行 */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          label="任务总数"
          value={String(summary.data?.tasksTotal ?? 0)}
          delta="+12 今日"
          deltaTone="up"
          sub={`成功率 ${Math.round((summary.data?.successRate ?? 0) * 100)}%`}
          loading={summary.loading}
          to="/workspace"
        />
        <MetricCard
          label="运行中"
          value={String(summary.data?.tasksRunning ?? 0)}
          delta={summary.data && summary.data.tasksRunning > 0 ? '有任务在执行' : '空闲'}
          deltaTone="neutral"
          loading={summary.loading}
          to="/workspace"
        />
        <MetricCard
          label="Token 消耗"
          value={formatTokens(summary.data?.tokensTotal ?? 0)}
          delta="+8.2%"
          deltaTone="up"
          sub={`今日 ${formatTokens(summary.data?.tokensToday ?? 0)}`}
          loading={summary.loading}
          to="/evaluation"
        />
        <MetricCard
          label="Skill 库"
          value={String(summary.data?.skillCount ?? 0)}
          delta="+2 本周"
          deltaTone="up"
          sub={`累计进化 ${summary.data?.skillEvolutions ?? 0} 次`}
          loading={summary.loading}
          to="/skills"
        />
      </div>

      {/* 图表行（Mock 标注只在页面级，验收 M2） */}
      <div className="grid gap-3 xl:grid-cols-5">
        <ChartCard
          title="任务趋势"
          loading={trends.loading}
          error={trends.error}
          onRetry={trends.reload}
          className="min-w-0 xl:col-span-3"
          extra={
            <ChartLegend
              items={[
                { label: '创建', color: CHART_SERIES_COLORS[0] },
                { label: '成功', color: CHART_SERIES_COLORS[1] },
                { label: '失败', color: CHART_SERIES_COLORS[5] },
              ]}
            />
          }
        >
          <TrendArea
            data={(trends.data?.taskTrend ?? []) as unknown as Record<string, string | number>[]}
            series={[
              { key: 'created', label: '创建', color: CHART_SERIES_COLORS[0] },
              { key: 'succeeded', label: '成功', color: CHART_SERIES_COLORS[1] },
              { key: 'failed', label: '失败', color: CHART_SERIES_COLORS[5] },
            ]}
          />
        </ChartCard>

        <ChartCard
          title="Token 消耗 · 按模型"
          loading={trends.loading}
          error={trends.error}
          onRetry={trends.reload}
          className="min-w-0 xl:col-span-2"
          extra={
            <ChartLegend
              items={[
                { label: 'GLM-5.3', color: CHART_SERIES_COLORS[0] },
                { label: 'Flash', color: CHART_SERIES_COLORS[1] },
              ]}
            />
          }
        >
          <StackedBar
            data={(trends.data?.tokenTrend ?? []) as unknown as Record<string, string | number>[]}
            series={[
              { key: 'glm53', label: 'GLM-5.3 (K)', color: CHART_SERIES_COLORS[0] },
              { key: 'flash', label: 'Flash (K)', color: CHART_SERIES_COLORS[1] },
            ]}
          />
        </ChartCard>
      </div>

      {/* 内容行 */}
      <div className="grid gap-3 xl:grid-cols-5">
        {/* 最近任务（整卡 min-w-0 防表格撑破，验收 M1） */}
        <section className="min-w-0 rounded-xl border border-border bg-surface shadow-card xl:col-span-3">
          <header className="flex items-center gap-2 p-4 pb-3">
            <h3 className="text-base font-medium">最近任务</h3>
            <Link to="/workspace" className="ml-auto text-xs text-primary hover:underline">
              查看全部
            </Link>
          </header>
          <div className="overflow-x-auto px-2 pb-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-2xs text-foreground-muted">
                  <th className="px-2 pb-2 font-medium">任务</th>
                  <th className="px-2 pb-2 font-medium">状态</th>
                  <th className="px-2 pb-2 font-medium">模型</th>
                  <th className="px-2 pb-2 text-right font-medium">耗时</th>
                  <th className="px-2 pb-2 text-right font-medium">Token</th>
                </tr>
              </thead>
              <tbody>
                {tasks.loading &&
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      <td colSpan={5} className="px-2 py-1.5">
                        <Skeleton className="h-6 w-full" />
                      </td>
                    </tr>
                  ))}
                {!tasks.loading &&
                  recent.map((t) => (
                    <tr key={t.id} className="border-t border-border transition-colors hover:bg-hover">
                      <td className="max-w-52 truncate px-2 py-2">
                        <Link to={`/workspace/${t.id}`} className="text-foreground hover:text-primary" title={t.title}>
                          {t.title}
                        </Link>
                      </td>
                      <td className="px-2 py-2">
                        <StatusBadge status={t.status} />
                      </td>
                      <td className="px-2 py-2">
                        <span className="rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-2xs text-foreground-secondary">
                          {modelLabel(t.model)}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono text-xs text-foreground-secondary">
                        {formatDuration(t.stats.durationMs)}
                      </td>
                      <td className="px-2 py-2 text-right font-mono text-xs text-foreground-secondary">
                        {formatTokens(t.stats.tokensIn + t.stats.tokensOut)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Agent 状态 */}
        <ChartCard title="Agent 状态" loading={agentStatus.loading} className="min-w-0 xl:col-span-1">
          <DonutChart
            data={(agentStatus.data?.items ?? []).map((it, i) => ({
              ...it,
              color: [CHART_SERIES_COLORS[1], CHART_SERIES_COLORS[4], DONUT_IDLE_COLOR][i] ?? CHART_SERIES_COLORS[i],
            }))}
            centerValue={agentStatus.data?.total ?? 0}
            centerLabel="在线 Agent"
          />
          <DonutLegend
            items={(agentStatus.data?.items ?? []).map((it, i) => ({
              ...it,
              color: [CHART_SERIES_COLORS[1], CHART_SERIES_COLORS[4], DONUT_IDLE_COLOR][i] ?? CHART_SERIES_COLORS[i],
            }))}
          />
        </ChartCard>

        {/* Skill 进化动态 + 系统健康 */}
        <section className="min-w-0 space-y-3 xl:col-span-1">
          <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
            <header className="mb-2 flex items-center gap-2">
              <h3 className="text-base font-medium">进化动态</h3>
            </header>
            <ul className="space-y-0.5">
              {skillEvents.loading && <Skeleton className="h-24 w-full" />}
              {skillEvents.data?.items.slice(0, 4).map((ev: SkillEvent) => {
                const meta = EVENT_ICON[ev.type]
                const Icon = meta.icon
                return (
                  <li key={ev.id} className="flex gap-2.5 rounded-lg px-1.5 py-1.5 transition-colors hover:bg-hover">
                    <Icon className={`mt-0.5 size-3.5 shrink-0 ${meta.cls}`} aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-xs leading-5 text-foreground-secondary">
                        <Link to="/skills" className="text-foreground hover:text-primary">
                          {ev.message.split('「')[1]?.split('」')[0] ?? 'Skill'}
                        </Link>{' '}
                        {ev.message.split('」')[1] ?? ev.message}
                      </p>
                      <TimeAgo value={ev.createdAt} />
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>

          <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
            <header className="mb-2 flex items-center gap-2">
              <h3 className="text-base font-medium">系统健康</h3>
            </header>
            <ul className="space-y-1.5">
              {health.data &&
                (
                  [
                    ['API', health.data.api],
                    ['PostgreSQL', health.data.postgres],
                    ['Redis', health.data.redis],
                    ['Chroma', health.data.chroma],
                  ] as const
                ).map(([name, s]) => (
                  <li key={name} className="flex items-center gap-2 text-xs text-foreground-secondary">
                    <StatusDot tone={s.status === 'ok' ? 'success' : 'failed'} />
                    {name}
                    <span className="ml-auto font-mono text-2xs text-foreground-muted">{s.latencyMs}ms</span>
                  </li>
                ))}
              {health.data?.mcp.map((m) => (
                <li key={m.name} className="flex items-center gap-2 text-xs text-foreground-secondary">
                  <StatusDot tone={m.status === 'ok' ? 'success' : 'failed'} />
                  MCP · {m.name}
                  <span className="ml-auto font-mono text-2xs text-foreground-muted">{m.latencyMs}ms</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </PageShell>
  )
}
