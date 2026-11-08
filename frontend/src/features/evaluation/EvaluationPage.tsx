import { PageShell } from '@/components/common/PageShell'
import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

/** Evaluation Center（docs/05 §6）：P2 交付评测图表 */
export default function EvaluationPage() {
  return (
    <PageShell title="Evaluation Center" description="成功率、模型对比、成本与进化效果" mock>
      <PhasePlaceholder
        phase={2}
        phaseName="资产与观测五页"
        scope="将包含：成功率 / 耗时 / Token 成本 / 压缩率 KPI、成功率趋势、GLM-5.3 与 Flash 模型对比、Skill 进化前后对比、上下文压缩效果与评测明细表。"
      />
    </PageShell>
  )
}
