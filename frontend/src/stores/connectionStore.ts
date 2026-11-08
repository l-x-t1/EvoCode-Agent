import { create } from 'zustand'

interface ConnectionState {
  /** 数据源模式：mock / live（来自 VITE_API_MODE） */
  apiMode: 'mock' | 'live'
  /** 后端健康状态（/system/health） */
  apiHealthy: boolean
  setApiHealthy: (ok: boolean) => void
  /** SSE 实时流连接状态（P1 接入 useRunStream） */
  sseConnected: boolean
  setSseConnected: (ok: boolean) => void
}

export const useConnectionStore = create<ConnectionState>()((set) => ({
  apiMode: import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock',
  apiHealthy: true,
  setApiHealthy: (apiHealthy) => set({ apiHealthy }),
  sseConnected: false,
  setSseConnected: (sseConnected) => set({ sseConnected }),
}))
