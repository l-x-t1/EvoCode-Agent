import { Toaster } from 'sonner'

export function ToastProvider() {
  return (
    <Toaster
      theme="dark"
      position="bottom-right"
      toastOptions={{
        style: {
          background: 'hsl(227 20% 11%)',
          border: '1px solid hsl(226 14% 17%)',
          color: 'hsl(220 25% 95%)',
        },
      }}
    />
  )
}
