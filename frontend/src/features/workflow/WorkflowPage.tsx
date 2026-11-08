import { useParams } from 'react-router-dom'
import { PageShell } from '@/components/common/PageShell'
import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

/** Workflow Center（docs/05 §5）：P2 交付 React Flow 执行图与回放 */
export default function WorkflowPage() {
  const { runId } = useParams()

  return (
    <PageShell
      title="Workflow Center"
      description={runId ? `运行 ${runId} 的多智能体执行图` : 'Multi-Agent 执行关系与状态可视化'}
      mock
    >
      <PhasePlaceholder
        phase={2}
        phaseName="资产与观测五页"
        scope="将包含：Planner / Executor / Reviewer / Replanner 执行图（React Flow）、运行列表、条件边标签、节点详情与执行回放。"
      />
    </PageShell>
  )
}
