import { useMemo } from 'react'
import { useViewerStore } from '../store'
import type { ContentItem } from '../types'

type Props = {
  items: ContentItem[]
  onSave?: () => void
}

export function Toolbar({ items, onSave }: Props) {
  const { scale, setScale, currentPage, setCurrentPage, filterTypes, toggleType, showLowConfidence, setShowLowConfidence } =
    useViewerStore()

  const typeCounts = useMemo(() => {
    const map = new Map<string, number>()
    items.forEach((i) => map.set(i.type, (map.get(i.type) ?? 0) + 1))
    return Array.from(map.entries())
  }, [items])

  return (
    <div className="toolbar">
      <div className="tool-group">
        <button onClick={() => setScale(Math.max(0.5, scale - 0.1))}>- 缩放</button>
        <span className="tool-label">{(scale * 100).toFixed(0)}%</span>
        <button onClick={() => setScale(Math.min(3, scale + 0.1))}>+ 缩放</button>
      </div>

      <div className="tool-group">
        <span className="tool-label">页码</span>
        <input
          type="number"
          min={1}
          value={currentPage}
          onChange={(e) => setCurrentPage(Number(e.target.value))}
          className="tool-input"
        />
      </div>

      <div className="tool-group filters">
        <span className="tool-label">图层</span>
        {typeCounts.map(([type, count]) => (
          <label key={type} className="tool-check">
            <input type="checkbox" checked={filterTypes.has(type)} onChange={() => toggleType(type)} /> {type} ({count})
          </label>
        ))}
      </div>

      <div className="tool-group">
        <label className="tool-check">
          <input type="checkbox" checked={showLowConfidence} onChange={(e) => setShowLowConfidence(e.target.checked)} />
          低置信度提示
        </label>
      </div>

      <div className="tool-group">
        <button onClick={onSave}>保存</button>
      </div>
    </div>
  )
}

