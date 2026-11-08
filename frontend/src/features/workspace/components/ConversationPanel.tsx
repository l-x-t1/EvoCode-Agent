import { SendHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { MessageBubble } from './MessageBubble'
import type { Message } from '@/types/api'

interface ConversationPanelProps {
  messages: Message[]
  loading?: boolean
  /** 任务运行中：输入置灰（插话 P1 后续开放） */
  locked?: boolean
  onSubmit?: (text: string) => void
  placeholder?: string
}

/** 左栏：对话消息流 + 输入框（docs/05 §2 F-W2/F-W3） */
export function ConversationPanel({ messages, loading, locked, onSubmit, placeholder }: ConversationPanelProps) {
  const [draft, setDraft] = useState('')

  const submit = () => {
    const text = draft.trim()
    if (!text || locked || !onSubmit) return
    onSubmit(text)
    setDraft('')
  }

  return (
    <div className="flex min-h-0 flex-col rounded-xl border border-border bg-surface">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3" aria-label="对话消息流">
        {loading &&
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
        {!loading && messages.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-foreground-muted">
            执行开始后，用户与各角色 Agent 的消息将显示在这里
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>
      <div className="border-t border-border p-2.5">
        <div className="rounded-lg border border-border bg-elevated focus-within:border-border-strong">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            disabled={locked}
            rows={2}
            placeholder={placeholder ?? (locked ? '任务执行中，插话功能将在后续阶段开放' : '描述你的需求…（Enter 发送，Shift+Enter 换行）')}
            className="w-full resize-none bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-foreground-muted focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="flex items-center justify-end px-2 pb-2">
            <Button size="sm" disabled={locked || !draft.trim()} onClick={submit} aria-label="发送">
              <SendHorizontal aria-hidden="true" />
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
