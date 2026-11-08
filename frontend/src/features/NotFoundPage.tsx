import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

/** 品牌化 404（docs/02 §2） */
export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-hover text-foreground-muted">
        <Compass className="size-6" aria-hidden="true" />
      </div>
      <p className="font-mono text-3xl font-semibold text-foreground">404</p>
      <p className="text-sm text-foreground-secondary">
        页面不存在或已被移动。
        <br />
        可从下方返回工作台，或使用侧边导航前往目标页面。
      </p>
      <Button asChild size="sm" className="mt-2">
        <Link to="/">返回 Dashboard</Link>
      </Button>
    </div>
  )
}
