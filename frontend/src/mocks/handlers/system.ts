import { http, HttpResponse } from 'msw'
import type { SystemHealth } from '@/types/api'

/** 系统健康（TopBar / Dashboard 系统面板） */
export const systemHandlers = [
  http.get('*/api/v1/system/health', async () => {
    const health: SystemHealth = {
      api: { status: 'ok', latencyMs: 12 },
      postgres: { status: 'ok', latencyMs: 3 },
      redis: { status: 'ok', latencyMs: 2 },
      chroma: { status: 'ok', latencyMs: 18 },
      mcp: [
        { name: 'filesystem', status: 'ok', latencyMs: 6 },
        { name: 'git', status: 'ok', latencyMs: 8 },
        { name: 'search', status: 'ok', latencyMs: 4 },
        { name: 'tests', status: 'ok', latencyMs: 11 },
      ],
    }
    return HttpResponse.json(health)
  }),
]
