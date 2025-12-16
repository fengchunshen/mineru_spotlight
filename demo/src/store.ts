import { create } from 'zustand'
import type { ContentItem } from './types'

type FilterTypes = Set<string>

interface ViewerState {
  scale: number
  currentPage: number
  activeId?: string
  hoverId?: string
  filterTypes: FilterTypes
  showLowConfidence: boolean
  setScale: (scale: number) => void
  setCurrentPage: (page: number) => void
  setActiveId: (id?: string) => void
  setHoverId: (id?: string) => void
  toggleType: (type: string) => void
  setFilterTypes: (types: FilterTypes) => void
  setShowLowConfidence: (v: boolean) => void
}

export const useViewerStore = create<ViewerState>((set) => ({
  scale: 1,
  currentPage: 1,
  filterTypes: new Set(),
  showLowConfidence: false,
  setScale: (scale) => set({ scale }),
  setCurrentPage: (currentPage) => set({ currentPage }),
  setActiveId: (activeId) => set({ activeId }),
  setHoverId: (hoverId) => set({ hoverId }),
  toggleType: (type) =>
    set((state) => {
      const next = new Set(state.filterTypes)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return { filterTypes: next }
    }),
  setFilterTypes: (types) => set({ filterTypes: types }),
  setShowLowConfidence: (v) => set({ showLowConfidence: v }),
}))

export const groupByPage = (items: ContentItem[]) => {
  const map = new Map<number, ContentItem[]>()
  items.forEach((item) => {
    const list = map.get(item.page_idx) ?? []
    list.push(item)
    map.set(item.page_idx, list)
  })
  return map
}

