import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

/**
 * MSW Worker（VITE_API_MODE=mock 时由 main.tsx 动态加载）。
 * live 模式下本目录整体不参与打包（动态 import 被 tree-shake）。
 */
export const worker = setupWorker(...handlers)
