import { Construction } from 'lucide-react'
import { EmptyState } from './EmptyState'

interface PhasePlaceholderProps {
  phase: number
  phaseName: string
  /** 该页面将包含什么（docs/05 对应章节） */
  scope: string
}

/**
 * Phase 0 占位内容：明确说明页面属于哪个阶段交付，不虚构功能。
 * P1/P2 起被真实页面整体替换。
 */
export function PhasePlaceholder({ phase, phaseName, scope }: PhasePlaceholderProps) {
  return (
    <EmptyState
      icon={Construction}
      title={`本页面将在阶段 ${phase}（${phaseName}）交付`}
      description={scope}
      className="border border-dashed border-border rounded-xl"
    />
  )
}
