import { AgentAvatar, agentRoleLabel } from '@/components/agents/AgentAvatar'
import { cn } from '@/lib/utils'
import { formatTime } from '@/lib/format'
import type { Message } from '@/types/api'

/** 会话消息（docs/05 §2 F-W2）：角色着色左边框 + 头像 */
export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <article
      className={cn(
        'rounded-lg border-l-2 bg-surface px-3 py-2.5',
        isUser ? 'border-agent-user' : 'border-agent-planner',
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <AgentAvatar role={message.role} size="sm" />
        <span className="text-xs font-medium text-foreground">{agentRoleLabel(message.role)}</span>
        <time className="ml-auto font-mono text-2xs text-foreground-muted">
          {formatTime(message.createdAt)}
        </time>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-6 text-foreground-secondary">{message.content}</p>
    </article>
  )
}
