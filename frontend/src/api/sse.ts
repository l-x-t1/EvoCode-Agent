/**
 * SSE 客户端（docs/06 §4）。
 * 基于 fetch + ReadableStream（而非 EventSource）：
 * - 支持自定义 Last-Event-ID 续传
 * - 断线指数退避重连（1s→2s→4s，上限 10s）
 * - 解析 event/id/data 帧，忽略 `: ping` 心跳注释
 */

export interface SseEvent {
  event: string
  id: number
  /** docs/06 §4 信封：{ v, seq, ts, runId, payload } */
  data: { v: number; seq: number; ts: string; runId: string; payload: unknown }
}

interface StreamOptions {
  path: string
  /** 首次连接的续传位点 */
  lastEventId?: number
  onEvent: (e: SseEvent) => void
  onOpen?: () => void
  onDown?: (reason: 'error' | 'aborted') => void
  /** 外部中断（组件卸载 / 切换运行） */
  signal: AbortSignal
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

export function connectEventStream({ path, lastEventId = 0, onEvent, onOpen, onDown, signal }: StreamOptions): () => void {
  // 内部控制器：外部 signal 触发时级联中止
  const controller = new AbortController()
  const onExternalAbort = () => controller.abort()
  if (signal.aborted) onExternalAbort()
  else signal.addEventListener('abort', onExternalAbort, { once: true })

  void (async () => {
    let retry = 0
    let cursor = lastEventId
    try {
      while (!controller.signal.aborted) {
        try {
          const res = await fetch(`${BASE}${path}`, {
            headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(cursor) },
            signal: controller.signal,
          })
          if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`)
          retry = 0
          onOpen?.()

          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          // 逐帧解析：帧以空行分隔；行以 event:/id:/data:/: 开头
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            let idx: number
            while ((idx = buffer.indexOf('\n\n')) >= 0) {
              const raw = buffer.slice(0, idx)
              buffer = buffer.slice(idx + 2)
              const parsed = parseFrame(raw)
              if (parsed) {
                cursor = parsed.id
                onEvent(parsed)
              }
            }
          }
          // 服务端关闭（剧本流保持长连；此处多为网络中断）
          throw new Error('stream closed')
        } catch {
          if (controller.signal.aborted) break
          await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** retry, 10_000)))
          retry += 1
        }
      }
    } finally {
      signal.removeEventListener('abort', onExternalAbort)
      if (!controller.signal.aborted) onDown?.('error')
      else onDown?.('aborted')
    }
  })()

  return () => controller.abort()
}

function parseFrame(raw: string): SseEvent | null {
  let event = 'message'
  let id = 0
  let data = ''
  for (const line of raw.split('\n')) {
    if (line.startsWith(':')) continue // 心跳注释
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('id:')) id = Number(line.slice(3).trim()) || 0
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  try {
    return { event, id, data: JSON.parse(data) }
  } catch {
    return null
  }
}
