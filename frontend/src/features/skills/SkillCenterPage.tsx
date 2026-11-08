import { useParams } from 'react-router-dom'
import { PageShell } from '@/components/common/PageShell'
import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

/** Skill Center（docs/05 §3）：P2 交付主从布局与候选审核 */
export default function SkillCenterPage() {
  const { skillId } = useParams()

  return (
    <PageShell
      title="Skill Center"
      description={skillId ? `Skill ${skillId} 详情` : 'Skill 库、版本管理与进化审核'}
      mock
    >
      <PhasePlaceholder
        phase={2}
        phaseName="资产与观测五页"
        scope="将包含：Skill 库列表（搜索 / 分类 / 状态筛选）、详情（概览 / 版本时间线 / 进化历史 / 评测对比）、候选 Skill 审核队列（批准 / 拒绝）。"
      />
    </PageShell>
  )
}
