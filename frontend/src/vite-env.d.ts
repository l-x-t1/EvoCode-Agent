/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** mock = MSW 模拟数据；live = 真实后端 */
  readonly VITE_API_MODE: 'mock' | 'live'
  /** REST 基础路径，默认 /api/v1 */
  readonly VITE_API_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
