import { dashboardHandlers } from './dashboard'
import { systemHandlers } from './system'
import { taskHandlers } from './tasks'

/** 全部 MSW handlers（按域拆分，docs/04 §5） */
export const handlers = [...systemHandlers, ...dashboardHandlers, ...taskHandlers]
