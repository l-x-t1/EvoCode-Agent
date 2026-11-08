import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Density = 'comfortable' | 'compact'

interface UiState {
  /** 侧边栏折叠（桌面端 232px ↔ 64px） */
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  /** 密度：舒适（默认）/ 紧凑，P2 生效（docs/03 §4） */
  density: Density
  setDensity: (d: Density) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      density: 'comfortable',
      setDensity: (density) => set({ density }),
    }),
    { name: 'evocode-ui' },
  ),
)
