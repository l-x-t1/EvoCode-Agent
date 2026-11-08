import { Home } from 'lucide-react'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router-dom'
import { ErrorState } from '@/components/common/ErrorState'
import { Button } from '@/components/ui/button'

/** 路由级错误边界（docs/02 §6）：404 之外的渲染异常统一在此兜底 */
export function RouteError() {
  const error = useRouteError()

  if (isRouteErrorResponse(error)) {
    return (
      <ErrorState
        title={`请求出错（${error.status}）`}
        error={new Error(error.statusText || '页面不可用')}
        action={
          <Button asChild variant="outline" size="sm">
            <Link to="/">
              <Home aria-hidden="true" />
              返回首页
            </Link>
          </Button>
        }
      />
    )
  }

  return (
    <ErrorState
      title="页面渲染异常"
      error={error}
      action={
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
            刷新页面
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/">返回首页</Link>
          </Button>
        </div>
      }
    />
  )
}
