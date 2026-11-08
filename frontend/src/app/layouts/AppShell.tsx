import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Suspense, type ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { MobileTabBar } from './MobileTabBar'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

function PageTransition({ locationKey, children }: { locationKey: string; children: ReactNode }) {
  const reduced = useReducedMotion()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={locationKey}
        initial={reduced ? { opacity: 0 } : { opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduced ? { opacity: 0 } : { opacity: 0, y: -2 }}
        transition={{ duration: reduced ? 0.12 : 0.18, ease: 'easeOut' }}
        className="flex min-h-full flex-col px-5 py-6 md:px-6"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}

/**
 * 应用壳层（docs/02 §1，M7 改造）：标准 app-shell 布局——
 * 根容器固定视口高度，仅 main 内部滚动；全高页面（Workspace/Workflow）
 * 通过 flex-1 + min-h-0 占满剩余空间，不再依赖 calc 魔法数字。
 */
export function AppShell() {
  const location = useLocation()

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-y-auto pb-16 lg:pb-0">
          <Suspense fallback={<PageLoading />}>
            <PageTransition locationKey={location.pathname}>
              <Outlet />
            </PageTransition>
          </Suspense>
        </main>
      </div>
      <MobileTabBar />
    </div>
  )
}

function PageLoading() {
  return (
    <div className="flex h-64 items-center justify-center text-sm text-foreground-muted" role="status" aria-live="polite">
      页面加载中…
    </div>
  )
}
