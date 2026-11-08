import { useParams } from 'react-router-dom'
import { PageShell } from '@/components/common/PageShell'
import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

/** Context Center（docs/05 §4）：P2 交付上下文仪表与记忆层级 */
export default function ContextCenterPage() {
  const { sessionId } = useParams()

  return (
    <PageShell
      title="Context Center"
      description={sessionId ? `上下文会话 ${sessionId}` : '上下文用量、压缩记录与长期记忆'}
      mock
    >
      <PhasePlaceholder
        phase={2}
        phaseName="资产与观测五页"
        scope="将包含：上下文窗口分段仪表、Token 分布随时间变化图、压缩事件时间线、四层记忆卡片与记忆检索测试器、历史摘要列表。"
      />
    </PageShell>
  )
}
