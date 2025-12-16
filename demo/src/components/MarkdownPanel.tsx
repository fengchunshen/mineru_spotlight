import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import type { ContentItem } from '../types'
import { useViewerStore } from '../store'
import { TYPE_COLORS } from '../constants'

type Props = {
  items: ContentItem[]
  imageBase: string
}

export function MarkdownPanel({ items, imageBase }: Props) {
  const { activeId, hoverId, setActiveId, setHoverId, setCurrentPage } = useViewerStore()

  const sortedItems = useMemo(
    () => {
      return [...items].sort((a, b) => {
        // 首先按页码排序
        if (a.page_idx !== b.page_idx) {
          return a.page_idx - b.page_idx
        }
        // 同一页内，按bbox的y坐标（top）排序
        if (Array.isArray(a.bbox) && Array.isArray(b.bbox) && a.bbox.length >= 2 && b.bbox.length >= 2) {
          const aY = a.bbox[1] // y0 (top)
          const bY = b.bbox[1] // y0 (top)
          if (aY !== bY) {
            return aY - bY
          }
          // 如果y坐标相同，按x坐标排序
          const aX = a.bbox[0] // x0 (left)
          const bX = b.bbox[0] // x0 (left)
          if (aX !== bX) {
            return aX - bX
          }
        }
        // 最后按id排序作为后备
        return a.id.localeCompare(b.id)
      })
    },
    [items],
  )

  // 按页面分组items
  const itemsByPage = useMemo(() => {
    const grouped = new Map<number, typeof sortedItems>()
    sortedItems.forEach((item) => {
      const pageItems = grouped.get(item.page_idx) || []
      pageItems.push(item)
      grouped.set(item.page_idx, pageItems)
    })
    return grouped
  }, [sortedItems])

  // 获取所有页面的索引并排序
  const pageIndices = useMemo(() => {
    return Array.from(itemsByPage.keys()).sort((a, b) => a - b)
  }, [itemsByPage])

  return (
    <div className="markdown-panel">
      {pageIndices.map((pageIdx) => {
        const pageItems = itemsByPage.get(pageIdx) || []
        const pageNumber = pageIdx + 1
        
        return (
          <div key={pageIdx} className="md-page-group">
            {pageItems.map((item) => {
              const isActive = activeId === item.id
              const isHover = hoverId === item.id
              const color = TYPE_COLORS[item.type] ?? '#94a3b8'
              
              // 将颜色转换为rgba格式用于背景
              const hexToRgba = (hex: string, alpha: number) => {
                const r = parseInt(hex.slice(1, 3), 16)
                const g = parseInt(hex.slice(3, 5), 16)
                const b = parseInt(hex.slice(5, 7), 16)
                return `rgba(${r}, ${g}, ${b}, ${alpha})`
              }
              
              const hoverBg = hexToRgba(color, 0.1)
              const activeBg = hexToRgba(color, 0.18)
              const activeShadow = hexToRgba(color, 0.2)
              
              return (
                <div
                  id={`md-${item.id}`}
                  key={item.id}
                  className={`md-segment ${isActive ? 'active' : ''} ${isHover ? 'hover' : ''}`}
                  style={{
                    '--segment-color': color,
                    '--segment-hover-bg': hoverBg,
                    '--segment-active-bg': activeBg,
                    '--segment-active-shadow': activeShadow,
                  } as React.CSSProperties}
                  onMouseEnter={() => {
                    setHoverId(item.id)
                  }}
                  onMouseLeave={() => {
                    setHoverId(undefined)
                  }}
                  onClick={() => {
                    setActiveId(item.id)
                    setCurrentPage(item.page_idx + 1)
                  }}
                >
                  <ReactMarkdown
                    remarkPlugins={[remarkMath]}
                    rehypePlugins={[rehypeKatex, rehypeRaw]}
                    components={{
                      img: (props) => {
                        // 处理图片路径：如果路径包含 images/ 前缀，则去掉；否则直接使用文件名
                        let imageSrc = props.src || ''
                        
                        // 如果路径是绝对路径（以 http:// 或 https:// 开头），直接使用
                        if (imageSrc.startsWith('http://') || imageSrc.startsWith('https://')) {
                          return (
                            // eslint-disable-next-line jsx-a11y/alt-text
                            <img {...props} src={imageSrc} className="md-img" />
                          )
                        }
                        
                        // 如果路径以 images/ 开头，去掉这个前缀
                        if (imageSrc.startsWith('images/')) {
                          imageSrc = imageSrc.replace(/^images\//, '')
                        }
                        
                        // 对文件名进行URL编码（处理特殊字符）
                        const encodedFileName = imageSrc
                          .split('/')
                          .map(part => encodeURIComponent(part))
                          .join('/')
                        
                        // 拼接完整路径
                        const finalSrc = `${imageBase}/${encodedFileName}`
                        
                        return (
                          // eslint-disable-next-line jsx-a11y/alt-text
                          <img 
                            {...props} 
                            src={finalSrc} 
                            className="md-img"
                            onError={() => {
                              // 如果图片加载失败，输出调试信息
                              console.error('图片加载失败:', finalSrc, '原始路径:', props.src)
                            }}
                          />
                        )
                      },
                    }}
                  >
                    {item.content || item.text || ''}
                  </ReactMarkdown>
                </div>
              )
            })}
            {/* 页面底部页码标识 */}
            <div className="md-page-number">
              <span>第 {pageNumber} 页</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

