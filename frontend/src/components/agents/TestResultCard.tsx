import { CheckCircle2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TestResult } from '@/types/api'

/** 测试结果卡（docs/05 §2 F-W7）：通过统计 + 失败用例终端样式 */
export function TestResultCard({ result }: { result: TestResult }) {
  const total = result.passed + result.failed + result.skipped
  const allPass = result.failed === 0

  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border bg-surface',
        allPass ? 'border-success/40' : 'border-danger/40',
      )}
    >
      <div className="flex flex-wrap items-center gap-3 px-3 py-2">
        {allPass ? (
          <CheckCircle2 className="size-4 text-success" aria-hidden="true" />
        ) : (
          <XCircle className="size-4 text-danger" aria-hidden="true" />
        )}
        <span className="text-xs text-foreground-secondary">
          测试回归
          <b className={cn('ml-2 font-mono', allPass ? 'text-success' : 'text-danger')}>
            {result.passed}/{total}
          </b>
          {result.skipped > 0 && <span className="ml-2 text-foreground-muted">{result.skipped} skipped</span>}
        </span>
      </div>
      {result.failures.length > 0 && (
        <div className="space-y-1.5 border-t border-border bg-background px-3 py-2.5">
          {result.failures.map((f) => (
            <div key={f.name} className="font-mono text-2xs leading-5">
              <p className="text-danger">✗ {f.name}</p>
              {f.message && <p className="pl-4 text-foreground-muted">{f.message}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
