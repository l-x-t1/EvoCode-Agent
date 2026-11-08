import { FileCode2 } from 'lucide-react'

interface DiffFileLite {
  path: string
  additions: number
  deletions: number
  patch: string
}

function PatchLine({ line }: { line: string }) {
  if (line.startsWith('@@'))
    return <div className="bg-hover px-3 py-0.5 font-mono text-2xs text-info">{line}</div>
  if (line.startsWith('+'))
    return <div className="bg-success-soft px-3 py-0.5 font-mono text-2xs text-success">{line}</div>
  if (line.startsWith('-'))
    return <div className="bg-danger-soft px-3 py-0.5 font-mono text-2xs text-danger">{line}</div>
  return <div className="px-3 py-0.5 font-mono text-2xs text-foreground-secondary">{line || ' '}</div>
}

/** 代码变更卡（docs/05 §2 F-W6）：单文件 unified diff，行级着色 */
export function DiffCard({ file }: { file: DiffFileLite }) {
  return (
    <details className="overflow-hidden rounded-xl border border-border bg-surface" open>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 transition-colors hover:bg-hover">
        <FileCode2 className="size-3.5 text-foreground-muted" aria-hidden="true" />
        <code className="truncate font-mono text-xs text-foreground">{file.path}</code>
        <span className="ml-auto font-mono text-2xs">
          <span className="text-success">+{file.additions}</span>{' '}
          <span className="text-danger">−{file.deletions}</span>
        </span>
      </summary>
      <div className="border-t border-border bg-background py-1">
        {file.patch.split('\n').map((line, i) => (
          <PatchLine key={i} line={line} />
        ))}
      </div>
    </details>
  )
}
