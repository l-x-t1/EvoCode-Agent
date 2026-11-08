import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@/styles/globals.css'

import { createRoot } from 'react-dom/client'
import { App } from './app/App'

/** mock 模式下启动 MSW（live 模式该分支被 tree-shake，docs/04 §5） */
async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_API_MODE !== 'mock') return
  const { worker } = await import('./mocks/browser')
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true })
}

enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(<App />)
})
