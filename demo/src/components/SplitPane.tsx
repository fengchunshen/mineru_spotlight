import { useRef, useState, type ReactNode } from 'react'

type Props = {
  left: ReactNode
  right: ReactNode
}

export function SplitPane({ left, right }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftWidth, setLeftWidth] = useState(50) // percent

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault()
    const container = containerRef.current
    if (!container) return
    const { width, left: offsetLeft } = container.getBoundingClientRect()
    const handleMove = (ev: MouseEvent) => {
      const delta = ev.clientX - offsetLeft
      const percent = Math.max(25, Math.min(75, (delta / width) * 100))
      setLeftWidth(percent)
    }
    const handleUp = () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
  }

  return (
    <div className="split-pane" ref={containerRef}>
      <div className="pane left" style={{ width: `${leftWidth}%` }}>
        {left}
      </div>
      <div className="divider" onMouseDown={startDrag} />
      <div className="pane right" style={{ width: `${100 - leftWidth}%` }}>
        {right}
      </div>
    </div>
  )
}

