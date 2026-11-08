import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { ThemeProvider } from './providers/ThemeProvider'
import { ToastProvider } from './providers/ToastProvider'

export function App() {
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
      <ToastProvider />
    </ThemeProvider>
  )
}
