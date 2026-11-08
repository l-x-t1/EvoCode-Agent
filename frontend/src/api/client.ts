import type { ApiErrorBody } from '@/types/api'

/** 统一错误：携带后端错误码，UI 层据此渲染（docs/06 §1） */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** 幂等键：可重复提交的操作自动携带（docs/06 §1） */
  idempotencyKey?: string
  /** 超时毫秒，默认 15s */
  timeoutMs?: number
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'
const DEFAULT_TIMEOUT = 15_000

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, idempotencyKey, timeoutMs = DEFAULT_TIMEOUT } = options

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const onExternalAbort = () => controller.abort()
  signal?.addEventListener('abort', onExternalAbort)

  try {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8'
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

    const res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    if (!res.ok) {
      let code = 'internal'
      let message = `请求失败（HTTP ${res.status}）`
      let details: unknown
      try {
        const parsed = (await res.json()) as ApiErrorBody
        if (parsed?.error) {
          code = parsed.error.code
          message = parsed.error.message
          details = parsed.error.details
        }
      } catch {
        // 非 JSON 错误体，保持默认文案
      }
      throw new ApiError(res.status, code, message, details)
    }

    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'timeout', '请求超时，请稍后重试')
    }
    throw new ApiError(0, 'network', '网络异常，请检查连接')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onExternalAbort)
  }
}

/** 生成幂等键（简单实现，P4 后可换成 crypto.randomUUID） */
export function idempotencyKey(): string {
  return `idem_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}
