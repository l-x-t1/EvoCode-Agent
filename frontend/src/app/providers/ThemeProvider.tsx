import { useEffect, type ReactNode } from 'react'

/**
 * 主题 Provider：当前仅 Dark（docs/03 §2）。
 * 变量分层保证未来新增 Light 主题时组件零改动。
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const root = document.documentElement
    root.classList.add('dark')
    root.dataset.theme = 'dark'
  }, [])
  return <>{children}</>
}
