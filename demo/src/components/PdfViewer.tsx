import { useEffect, useMemo, useRef, useState } from 'react'
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type PDFPageProxy } from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { ContentItem, ViewerConfig } from '../types'
import { LOW_CONF_THRESHOLD, TYPE_COLORS } from '../constants'
import { useViewerStore } from '../store'

// 类型翻译映射
const TYPE_LABELS: Record<string, string> = {
  text: '文本',
  title: '标题',
  table: '表格',
  image: '图片',
  formula: '公式',
  header: '页眉',
  footer: '页脚',
  list: '列表',
  aside_text: '侧边文本',
  page_number: '页码',
}

// pdf.js worker
GlobalWorkerOptions.workerSrc = pdfWorker

type PageViewportMeta = {
  width: number
  height: number
}

type Props = {
  items: ContentItem[]
  config: ViewerConfig
}

const bboxToRect = (
  bbox: [number, number, number, number],
  page: PageViewportMeta,
  normalizedTo = 1000,
) => {
  const [x0, y0, x1, y1] = bbox
  const scaleX = page.width / normalizedTo
  const scaleY = page.height / normalizedTo
  const x = x0 * scaleX
  const y = y0 * scaleY
  const w = (x1 - x0) * scaleX
  const h = (y1 - y0) * scaleY
  return { x, y, w, h }
}

export function PdfViewer({ items, config }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const canvasRefs = useRef<Record<number, HTMLCanvasElement | null>>({})
  const overlayRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const basePageWidthRef = useRef<number | null>(null)

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [pageMeta, setPageMeta] = useState<Record<number, PageViewportMeta>>({})
  const [hasFit, setHasFit] = useState(false)
  const { scale, setScale, activeId, hoverId, setActiveId, setHoverId, filterTypes, showLowConfidence } =
    useViewerStore()

  const normalizedTo = config.bboxNormalizedTo ?? 1000

  useEffect(() => {
    let mounted = true
    getDocument(config.pdfUrl).promise.then((d) => {
      if (mounted) setDoc(d)
    })
    return () => {
      mounted = false
    }
  }, [config.pdfUrl])

  const pages = useMemo(() => (doc ? Array.from({ length: doc.numPages }, (_, i) => i + 1) : []), [doc])

  // 计算自适应缩放，避免 CSS 拉伸导致 bbox 错位
  // 按容器宽度自适应一次，避免初始渲染比例不正确；宽度变化时重算
  useEffect(() => {
    if (!doc) return
    const computeFit = async () => {
      const container = containerRef.current
      if (!container) return
      if (!basePageWidthRef.current) {
        const page = await doc.getPage(1)
        const viewport = page.getViewport({ scale: 1 })
        basePageWidthRef.current = viewport.width
      }
      const baseWidth = basePageWidthRef.current
      if (!baseWidth) return
      const available = container.clientWidth
      if (available <= 0) return
      const fit = available / baseWidth
      setScale(fit)
      setHasFit(true)
    }
    computeFit()
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(() => computeFit())
    observer.observe(el)
    return () => observer.disconnect()
  }, [doc, setScale])

  const renderPage = async (pageNumber: number, pageScale: number) => {
    if (!doc) return
    const page: PDFPageProxy = await doc.getPage(pageNumber)
    const viewport = page.getViewport({ scale: pageScale })
    setPageMeta((prev) => ({ ...prev, [pageNumber]: { width: viewport.width, height: viewport.height } }))
    const canvas = canvasRefs.current[pageNumber]
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return
    const outputScale = window.devicePixelRatio || 1
    canvas.width = viewport.width * outputScale
    canvas.height = viewport.height * outputScale
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    context.setTransform(outputScale, 0, 0, outputScale, 0, 0)
    await page.render({ canvasContext: context, viewport, canvas }).promise
  }

  // 共享滚动容器下，直接渲染全部页面，避免翻页时早期页面被卸载
  const visiblePages = pages

  useEffect(() => {
    if (!hasFit) return
    visiblePages.forEach((p) => renderPage(p, scale))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, scale, visiblePages, hasFit])

  const filteredItems = useMemo(() => {
    if (!filterTypes.size) return items
    return items.filter((i) => filterTypes.has(i.type))
  }, [items, filterTypes])

  const groupedByPage = useMemo(() => {
    const map = new Map<number, ContentItem[]>()
    filteredItems.forEach((item) => {
      const list = map.get(item.page_idx) ?? []
      list.push(item)
      map.set(item.page_idx, list)
    })
    return map
  }, [filteredItems])

  // 滚动逻辑已移至 App.tsx 统一处理

  return (
    <div className="pdf-viewer" ref={containerRef}>
      {visiblePages.map((pageNumber) => {
        const meta = pageMeta[pageNumber]
        const itemsForPage = groupedByPage.get(pageNumber - 1) ?? []
        return (
          <div
            key={pageNumber}
            className="pdf-page"
            ref={(el) => {
              pageRefs.current[pageNumber] = el
            }}
            style={{ minHeight: meta ? meta.height : 400 }}
          >
            <div className="pdf-page-inner" style={{ position: 'relative' }}>
              <canvas
                ref={(el) => {
                  canvasRefs.current[pageNumber] = el
                }}
              />
              {meta && (
                <div
                  className="overlay-layer"
                  ref={(el) => {
                    overlayRefs.current[pageNumber] = el
                  }}
                  style={{ width: meta.width, height: meta.height }}
                >
                  <svg width={meta.width} height={meta.height}>
                    {itemsForPage.map((item) => {
                      const { x, y, w, h } = bboxToRect(item.bbox, meta, normalizedTo)
                      const color = TYPE_COLORS[item.type] ?? '#94a3b8'
                      const active = activeId === item.id
                      const hover = hoverId === item.id
                      const lowConf = showLowConfidence && item.score !== undefined && item.score < LOW_CONF_THRESHOLD
                      const fill = active || hover ? color : 'none'
                      // 加深hover效果，使其更明显，与右侧markdown保持一致
                      const fillOpacity = active ? 0.18 : hover ? 0.15 : 0
                      const stroke = lowConf ? '#ef4444' : color
                      const strokeDasharray = lowConf ? '4 3' : 'none'
                      // 纤细的边框
                      const strokeWidth = active ? 1 : hover ? 1 : 0.5
                      const typeLabel = TYPE_LABELS[item.type] || item.type
                      
                      return (
                        <g
                          key={item.id}
                          onMouseEnter={() => setHoverId(item.id)}
                          onMouseLeave={() => setHoverId(undefined)}
                          onClick={() => setActiveId(item.id)}
                        >
                          <rect
                            x={x}
                            y={y}
                            width={w}
                            height={h}
                            fill={fill}
                            fillOpacity={fillOpacity}
                            stroke={stroke}
                            strokeWidth={strokeWidth}
                            strokeDasharray={strokeDasharray}
                            vectorEffect="non-scaling-stroke"
                            pointerEvents="all"
                            className={active ? 'bbox active' : hover ? 'bbox hover' : 'bbox'}
                          />
                          {/* 悬浮时显示类型标签 */}
                          {hover && (
                            <g>
                              <rect
                                x={x - 30}
                                y={y - 2}
                                width={28}
                                height={16}
                                fill="none"
                                stroke={color}
                                strokeWidth={1}
                                rx={0}
                                ry={0}
                              />
                              <text
                                x={x - 16}
                                y={y + 8}
                                fill={color}
                                fontSize="11"
                                fontWeight="600"
                                textAnchor="middle"
                                fontFamily="Times New Roman, Times, serif"
                                dominantBaseline="middle"
                              >
                                {typeLabel}
                              </text>
                            </g>
                          )}
                          {(hover || active) && (
                            <title>
                              {item.type}
                              {item.score !== undefined ? ` | score: ${item.score.toFixed(2)}` : ''}
                            </title>
                          )}
                        </g>
                      )
                    })}
                  </svg>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

