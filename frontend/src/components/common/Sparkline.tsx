import { CHART_SERIES_COLORS } from '@/components/charts/chartTheme'

/** 迷你趋势线（MetricCard 内嵌，纯 SVG 不依赖图表库） */
export function Sparkline({
  data,
  color = CHART_SERIES_COLORS[0],
  width = 96,
  height = 28,
  className,
}: {
  data: number[]
  color?: string
  width?: number
  height?: number
  className?: string
}) {
  if (data.length < 2) return null
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const step = width / (data.length - 1)
  const points = data.map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - ((v - min) / range) * (height - 6)).toFixed(1)}`)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} aria-hidden="true">
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
    </svg>
  )
}
