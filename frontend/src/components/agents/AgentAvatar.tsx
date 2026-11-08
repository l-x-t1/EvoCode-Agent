import { Eye, ListChecks, RefreshCw, Terminal, User, Bot, type LucideIcon } from 'lucide-react'
import type { AgentRole } from '@/types/api'
import { cn } from '@/lib/utils'

const ROLE_ICON: Record<AgentRole, LucideIcon> = {
  planner: ListChecks,
  executor: Terminal,
  reviewer: Eye,
  replanner: RefreshCw,
  user: User,
  system: Bot,
}

const ROLE_BG: Record<AgentRole, string> = {
  planner: 'bg-agent-planner',
  executor: 'bg-agent-executor',
  reviewer: 'bg-agent-reviewer',
  replanner: 'bg-agent-replanner',
  user: 'bg-agent-user',
  system: 'bg-elevated',
}

interface AgentAvatarProps {
  role: AgentRole
  size?: 'sm' | 'md'
  className?: string
}

/** Agent 角色标识：角色色圆角方块 + 角色图标（docs/03 §5.2） */
export function AgentAvatar({ role, size = 'md', className }: AgentAvatarProps) {
  const Icon = ROLE_ICON[role]
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-lg text-white',
        ROLE_BG[role],
        size === 'md' ? 'size-7' : 'size-5',
        className,
      )}
      title={role}
    >
      <Icon className={size === 'md' ? 'size-3.5' : 'size-3'} aria-hidden="true" />
    </span>
  )
}

const ROLE_LABEL: Record<AgentRole, string> = {
  planner: 'Planner',
  executor: 'Executor',
  reviewer: 'Reviewer',
  replanner: 'Replanner',
  user: '用户',
  system: '系统',
}

export const agentRoleLabel = (role: AgentRole): string => ROLE_LABEL[role]
