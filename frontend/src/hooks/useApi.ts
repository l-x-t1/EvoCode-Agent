import { useCallback, useEffect, useRef, useState } from 'react'

interface UseApiResult<T> {
  data: T | null
  loading: boolean
  error: unknown
  reload: () => void
}

/** 轻量请求 Hook（Phase 0~3 不引入 TanStack Query，docs/04 §1） */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[]): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fnRef
      .current()
      .then((d) => {
        if (!controller.signal.aborted) setData(d)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, loading, error, reload }
}
