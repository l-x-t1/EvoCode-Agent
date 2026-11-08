import { NavLink, useParams } from 'react-router-dom'
import { PageShell } from '@/components/common/PageShell'
import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'
import { cn } from '@/lib/utils'

const SECTIONS = [
  { key: 'models', label: '模型配置' },
  { key: 'routing', label: '模型路由策略' },
  { key: 'mcp', label: 'MCP 配置' },
  { key: 'permissions', label: '工具权限' },
  { key: 'system', label: '系统参数' },
] as const

type SectionKey = (typeof SECTIONS)[number]['key']

const SECTION_SCOPE: Record<SectionKey, string> = {
  models: 'GLM API Key（脱敏）、base URL、温度 / max_tokens、连通性测试。',
  routing: '复杂度阈值规则表（简单任务 → Flash，复杂任务 → 5.3）、规则启停与默认模型。',
  mcp: 'MCP Server 列表（stdio / SSE）、连接状态、工具发现与启用开关。',
  permissions: '工具 × 策略矩阵（auto / require_approval / disabled）与风险级别标注。',
  system: '上下文窗口大小、压缩阈值、失败重试次数、沙箱开关、并发上限。',
}

const isSection = (v: string | undefined): v is SectionKey =>
  !!v && SECTIONS.some((s) => s.key === v)

/** Settings（docs/05 §7）：页内二级导航，section 写入 URL（docs/02 §3） */
export default function SettingsPage() {
  const { section } = useParams()
  const active: SectionKey = isSection(section) ? section : 'models'

  return (
    <PageShell title="Settings" description="模型、MCP、工具权限与系统参数" mock>
      <div className="flex flex-col gap-6 md:flex-row">
        {/* 二级导航：<md 顶部横向滚动，>=md 左列 */}
        <nav
          aria-label="设置分组"
          className="flex shrink-0 gap-1 overflow-x-auto md:w-48 md:flex-col md:overflow-visible"
        >
          {SECTIONS.map((s) => (
            <NavLink
              key={s.key}
              to={`/settings/${s.key}`}
              className={({ isActive }) =>
                cn(
                  'whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-foreground-secondary transition-colors hover:bg-hover hover:text-foreground',
                  isActive && 'bg-primary-soft font-medium text-foreground',
                )
              }
            >
              {s.label}
            </NavLink>
          ))}
        </nav>

        <section className="min-w-0 flex-1">
          <h2 className="mb-4 text-lg font-semibold text-foreground">
            {SECTIONS.find((s) => s.key === active)?.label}
          </h2>
          <PhasePlaceholder phase={2} phaseName="资产与观测五页" scope={SECTION_SCOPE[active]} />
        </section>
      </div>
    </PageShell>
  )
}
