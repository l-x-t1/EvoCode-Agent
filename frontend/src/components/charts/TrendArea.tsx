import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AXIS_TICK, CARTESIAN_GRID, TOOLTIP_ITEM_STYLE, TOOLTIP_LABEL_STYLE, TOOLTIP_STYLE } from './chartTheme'

export interface TrendSeries {
  key: string
  label: string
  color: string
  dashed?: boolean
}

/** 趋势面积图（docs/05 §1 任务趋势）：多系列半透明面积 + 实线描边 */
export function TrendArea({
  data,
  series,
  height = 232,
}: {
  data: Record<string, string | number>[]
  series: TrendSeries[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid {...CARTESIAN_GRID} />
        <XAxis dataKey="date" tick={AXIS_TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
        {series.map((s) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={1.6}
            strokeDasharray={s.dashed ? '4 3' : undefined}
            fill={s.color}
            fillOpacity={0.1}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}
