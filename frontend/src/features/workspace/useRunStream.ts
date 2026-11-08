import { useEffect, useRef } from 'react'
import { connectEventStream } from '@/api/sse'
import { endpoints } from '@/api/endpoints'
import { useConnectionStore } from '@/stores/connectionStore'
import { useRunStore } from './runStore'

/**
 * SSE 订阅 Hook（docs/04 §3 useRunStream）：
 * - 挂载时初始化 runStore 并连接 `/runs/:runId/events`
 * - 断线自动重连，携带最后 seq 续传（Last-Event-ID）
 * - 连接状态写入 connectionStore（侧边栏/顶栏展示）
 */
export function useRunStream(runId: string | undefined): void {
  const initRun = useRunStore((s) => s.initRun)
  const applyEvent = useRunStore((s) => s.applyEvent)
  const setStream = useRunStore((s) => s.setStream)
  const setSseConnected = useConnectionStore((s) => s.setSseConnected)
  const lastSeqRef = useRef(0)

  useEffect(() => {
    if (!runId) {
      setSseConnected(false)
      return
    }
    initRun(runId)
    lastSeqRef.current = useRunStore.getState().state.lastSeq

    const controller = new AbortController()
    const disconnect = connectEventStream({
      path: endpoints.runEventsStream(runId),
      lastEventId: lastSeqRef.current,
      signal: controller.signal,
      onOpen: () => {
        setStream('live')
        setSseConnected(true)
      },
      onEvent: (e) => {
        lastSeqRef.current = Math.max(lastSeqRef.current, e.id)
        applyEvent(e)
      },
      onDown: (reason) => {
        if (reason !== 'aborted') setStream('down')
        setSseConnected(false)
      },
    })

    return () => {
      controller.abort()
      disconnect()
      setStream('idle')
      setSseConnected(false)
    }
  }, [runId, initRun, applyEvent, setStream, setSseConnected])
}
