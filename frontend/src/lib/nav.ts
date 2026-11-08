import {
  BrainCircuit,
  LayoutDashboard,
  Library,
  Settings2,
  Sparkles,
  TrendingUp,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** 路径完全匹配才高亮（如 Dashboard 的 `/`） */
  end?: boolean
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

/** 侧边栏导航分组（docs/02 §1） */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: '概览',
    items: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true }],
  },
  {
    label: '工作',
    items: [{ to: '/workspace', label: 'Agent Workspace', icon: Sparkles }],
  },
  {
    label: '资产',
    items: [
      { to: '/skills', label: 'Skill Center', icon: Library },
      { to: '/context', label: 'Context Center', icon: BrainCircuit },
    ],
  },
  {
    label: '观测',
    items: [
      { to: '/workflow', label: 'Workflow Center', icon: Workflow },
      { to: '/evaluation', label: 'Evaluation Center', icon: TrendingUp },
    ],
  },
  {
    label: '系统',
    items: [{ to: '/settings/models', label: 'Settings', icon: Settings2 }],
  },
]
