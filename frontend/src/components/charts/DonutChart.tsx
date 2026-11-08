import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { TOOLTIP_ITEM_STYLE, TOOLTIP_STYLE } from './chartTheme'

export interface DonutDatum {
  name: string
  value: number
  color: string
}

/** 环形图（docs/05 §1 Agent 状态分布）：中心数值 + 图例由父组件渲染 */
export function DonutChart({
  data,
  height = 160,
  centerValue,
  centerLabel,
}: {
  data: DonutDatum[]
  height?: number
  centerValue?: string | number
  centerLabel?: string
}) {
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="62%"
            outerRadius="88%"
            paddingAngle={2}
            strokeWidth={0}
            isAnimationActive={false}
          >
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} />
            ))}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
        </PieChart>
      </ResponsiveContainer>
      {(centerValue !== undefined || centerLabel) && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {centerValue !== undefined && (
            <span className="font-mono text-[22px] font-semibold text-foreground">{centerValue}</span>
          )}
          {centerLabel && <span className="text-xs text-foreground-muted">{centerLabel}</span>}
        </div>
      )}
    </div>
  )
}

/** 环形图图例列表（右侧数值对齐） */
export function DonutLegend({ items, unit = '' }: { items: DonutDatum[]; unit?: string }) {
  return (
    <ul className="mt-3 space-y-1.5">
      {items.map((it) => (
        <li key={it.name} className="flex items-center gap-2 text-xs text-foreground-secondary">
          <i className="inline-block size-2 rounded-sm" style={{ background: it.color }} aria-hidden="true" />
          {it.name}
          <b className="ml-auto font-mono font-medium text-foreground">
            {it.value}
            {unit}
          </b>
        </li>
      ))}
    </ul>
  )
}
