/** Token 数格式化：1234 -> 1.2K，4200000 -> 4.2M */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) {
    const k = n / 1000
    return `${k >= 100 ? Math.round(k) : k.toFixed(1)}K`
  }
  return `${(n / 1_000_000).toFixed(1)}M`
}

/** 毫秒时长：75000 -> "1m 15s"，4200 -> "4s"，5400000 -> "1h 30m" */
export function formatDuration(ms: number): string {
  if (ms < 0) return '—'
  const totalSec = Math.floor(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${s.toString().padStart(2, '0')}s`
}

/** 相对时间：ISO 字符串或 Date -> "3 分钟前" */
export function timeAgo(input: string | Date): string {
  const date = typeof input === 'string' ? new Date(input) : input
  const diffMs = Date.now() - date.getTime()
  if (Number.isNaN(diffMs)) return '—'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN')
}

/** 本地时间显示（表格时间戳用） */
export function formatTime(input: string | Date): string {
  const date = typeof input === 'string' ? new Date(input) : input
  return date.toLocaleString('zh-CN', { hour12: false })
}
