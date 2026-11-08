import { useSearchParams } from 'react-router-dom'

/**
 * 把「页内 tab / 筛选 / 选中项」写入 search params（docs/02 §3 约定），
 * 保证刷新、分享、后退一致。
 */
export function useSearchParamsState(
  key: string,
  defaultValue: string,
): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams()
  const value = params.get(key) ?? defaultValue

  const setValue = (next: string) => {
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev)
        if (next === defaultValue) {
          copy.delete(key)
        } else {
          copy.set(key, next)
        }
        return copy
      },
      { replace: true },
    )
  }

  return [value, setValue]
}
