import { useEffect, useMemo, useRef, useState } from 'react'
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type PDFPageProxy } from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { ContentItem, ViewerConfig } from '../types'
import { LOW_CONF_THRESHOLD, TYPE_COLORS } from '../constants'
import { useViewerStore } from '../store'

// 类型翻译映射（根据文档提供的中文说明）
const TYPE_LABELS: Record<string, string> = {
  text: '文本',
  title: '标题',
  // 后端有时使用 equation，我们已在加载时统一归一到 formula，这里用“行间公式”的中文说明
  formula: '行间公式',
  image: '图片',
  image_caption: '图片描述',
  image_footnote: '图片脚注',
  table: '表格',
  table_caption: '表格描述',
  table_footnote: '表格脚注',
  phonetic: '拼音',
  code: '代码块',
  code_caption: '代码描述',
  ref_text: '参考文献',
  algorithm: '算法块',
  list: '列表',
  header: '页眉',
  footer: '页脚',
  page_number: '页码',
  aside_text: '装订线旁注',
  page_footnote: '页面脚注',
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

// 将已经归一化到 [0, normalizedTo] 的 bbox 线性映射到当前 PDF 页面的 viewport。
// 后端明确保证 bbox 坐标落在 0–1000 之间，因此这里只需要做简单比例缩放，不做任何额外偏移或自适应。
const bboxToRect = (
  bbox: [number, number, number, number],
  page: PageViewportMeta,
  normalizedTo: number,
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
  // 首次自适应时做一到两帧的延迟，避免在容器尺寸尚未稳定时就计算缩放比例
  const hasRequestedInitialFitRef = useRef(false)

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [pageMeta, setPageMeta] = useState<Record<number, PageViewportMeta>>({})
  const [hasFit, setHasFit] = useState(false)
  const { scale, setScale, activeId, hoverId, setActiveId, setHoverId, filterTypes, showLowConfidence } =
    useViewerStore()

  const normalizedTo = config.bboxNormalizedTo ?? 1000
  const [isRenderingInitialPages, setIsRenderingInitialPages] = useState(true)

  useEffect(() => {
    let mounted = true
    // 当切换到新的 PDF 时，重置基础宽度、缩放计算标记和页面元信息，避免沿用上一个文档的参数导致 bbox 错位
    basePageWidthRef.current = null
    setHasFit(false)
    setPageMeta({})

    // 为了正确渲染中文等 CJK 字体，需要为 pdf.js 提供 CMap 和标准字体数据路径。
    // 这里直接使用与项目依赖版本匹配的 jsDelivr CDN 资源，避免本地拷贝体积过大。
    getDocument({
      url: config.pdfUrl,
      cMapUrl: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.449/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.449/standard_fonts/',
    }).promise.then((d) => {
      if (mounted) setDoc(d)
    })
    return () => {
      mounted = false
    }
  }, [config.pdfUrl])

  const pages = useMemo(() => (doc ? Array.from({ length: doc.numPages }, (_, i) => i + 1) : []), [doc])

  // 计算自适应缩放，避免 CSS 拉伸导致 bbox 错位
  // 首次挂载时延迟一到两帧再计算，确保容器布局和宽度已经稳定；后续仅在尺寸变化时即时重算
  useEffect(() => {
    if (!doc) return
    const computeFit = async (withDelay: boolean) => {
      if (withDelay) {
        // 使用两次 requestAnimationFrame，把计算推迟到下一轮布局之后
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => resolve())
          })
        })
      }

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
    // 首次自适应：带延迟，避免用到未稳定的容器宽度；随后再补一次无延迟计算，模拟“用户轻点一次缩放”后的稳定状态
    if (!hasRequestedInitialFitRef.current) {
      hasRequestedInitialFitRef.current = true
      void computeFit(true)
      // 再补偿性计算一次，确保在布局完全稳定之后重新取一次精确宽度
      setTimeout(() => {
        void computeFit(false)
      }, 350)
    } else {
      void computeFit(false)
    }
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      // 尺寸变化时不再额外延迟，直接重算
      void computeFit(false)
    })
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
    const renderAll = async () => {
      // 先渲染前两页，尽快让用户看到内容，其余页面在后续循环中逐步绘制
      const firstBatch = visiblePages.slice(0, 2)
      await Promise.all(firstBatch.map((p) => renderPage(p, scale)))
      setIsRenderingInitialPages(false)
      const rest = visiblePages.slice(2)
      for (const p of rest) {
        // 顺序渲染剩余页面，避免一次性占用主线程过久
        // eslint-disable-next-line no-await-in-loop
        await renderPage(p, scale)
      }
    }
    void renderAll()
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
      {(!doc || isRenderingInitialPages) && (
        <div className="pdf-skeleton">
          {[0, 1].map((i) => (
            <div key={i} className="pdf-skeleton-page">
              {/* 顶部标题行 */}
              <div className="pdf-skeleton-row pdf-skeleton-row--title" />
              {/* 副标题行 */}
              <div className="pdf-skeleton-row pdf-skeleton-row--subtitle" />

              {/* 中部大块区域，模拟插图 / 表格 */}
              <div className="pdf-skeleton-block" />

              {/* 下方多行正文骨架 */}
              <div className="pdf-skeleton-lines">
                <div className="pdf-skeleton-row" />
                <div className="pdf-skeleton-row" />
                <div className="pdf-skeleton-row" />
                <div className="pdf-skeleton-row pdf-skeleton-row--short" />
              </div>

              <div className="pdf-skeleton-lines">
                <div className="pdf-skeleton-row" />
                <div className="pdf-skeleton-row" />
                <div className="pdf-skeleton-row pdf-skeleton-row--short" />
              </div>
            </div>
          ))}
        </div>
      )}
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

