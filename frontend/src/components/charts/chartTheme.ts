/**
 * 图表统一主题（docs/03 §2.5）。
 * 色板按序取用；网格/轴/tooltip 全部从 token 派生。
 */
export const CHART_SERIES_COLORS = [
  '#8b5cf6', // violet
  '#3b82f6', // blue
  '#06b6d4', // cyan
  '#10b981', // emerald
  '#f59e0b', // amber
  '#f43f5e', // rose
  '#d946ef', // fuchsia
  '#64748b', // slate
] as const

/** Recharts 轴文字样式 */
export const AXIS_TICK = {
  fill: 'hsl(220 10% 46%)',
  fontSize: 11,
} as const

/** Recharts 笛卡尔网格：低对比水平线 */
export const CARTESIAN_GRID = {
  stroke: 'hsl(226 14% 17%)',
  strokeOpacity: 0.6,
  vertical: false,
} as const

/** Recharts tooltip 容器样式（复用 elevated 卡片） */
export const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(227 20% 11%)',
  border: '1px solid hsl(226 14% 17%)',
  borderRadius: 8,
  fontSize: 12,
  color: 'hsl(220 25% 95%)',
  boxShadow: '0 8px 24px rgb(0 0 0 / 50%)',
} as const

export const TOOLTIP_ITEM_STYLE = { color: 'hsl(220 25% 95%)' } as const

export const TOOLTIP_LABEL_STYLE = {
  color: 'hsl(220 12% 68%)',
  marginBottom: 4,
} as const

/** 环形图「空闲/无状态」分段中性色（Dashboard Agent 状态） */
export const DONUT_IDLE_COLOR = '#3a4256' as const

/**
 * ContextGauge 分段配色（语义段 → 图表色板，S1 收敛单一来源）。
 * system/skill/memory/history/working/compressed
 */
export const CONTEXT_SEGMENT_COLORS = {
  system: '#64748b',
  skill: '#8b5cf6',
  memory: '#06b6d4',
  history: '#3b82f6',
  working: '#10b981',
  compressed: '#f59e0b',
} as const
