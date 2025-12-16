import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import type { ViewerConfig, ContentItem } from './types'
import { PdfViewer } from './components/PdfViewer'
import { MarkdownPanel } from './components/MarkdownPanel'
import { SplitPane } from './components/SplitPane'
import { Toolbar } from './components/Toolbar'
import { useViewerStore } from './store'
import debounce from 'lodash.debounce'

const base = '/export'
const url = (name: string) => `${base}/${encodeURI(name)}`

const config: ViewerConfig = {
  pdfUrl: url('RoBERTa-wwm-ext Fine-Tuning for Chinese_origin.pdf'),
  contentListUrl: url('RoBERTa-wwm-ext Fine-Tuning for Chinese_content_list.json'),
  markdownUrl: url('RoBERTa-wwm-ext Fine-Tuning for Chinese.md'),
  imageBase: `${base}/images`,
  bboxNormalizedTo: 1000,
}

function App() {
  const [items, setItems] = useState<ContentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { activeId, setCurrentPage, setFilterTypes, setActiveId } = useViewerStore()
  const pdfScrollRef = useRef<HTMLDivElement>(null)
  const mdScrollRef = useRef<HTMLDivElement>(null)
  const suppressScrollSyncRef = useRef(false)
  const suppressTimerRef = useRef<number | null>(null)
  const lastSyncedPageRef = useRef<number | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(config.contentListUrl)
        const data = (await res.json()) as any[]
        const mapped: ContentItem[] = data.map((item, idx) => {
          let content = item.content ?? item.text
          
          // 根据不同类型生成对应的markdown内容
          if (!content) {
            switch (item.type) {
              case 'image':
                // image类型：使用img_path生成markdown图片引用
                if (item.img_path) {
                  content = `![](${item.img_path})`
                }
                break
              
              case 'list':
                // list类型：将list_items数组转换为markdown列表
                if (item.list_items && Array.isArray(item.list_items)) {
                  // 确保列表项之间有正确的格式，每个列表项单独一行
                  content = item.list_items
                    .map(item => item.trim())
                    .filter(item => item.length > 0)
                    .join('\n')
                }
                break
              
              case 'table':
                // table类型：使用table_body（HTML格式），并添加caption
                const tableParts: string[] = []
                if (item.table_caption && Array.isArray(item.table_caption) && item.table_caption.length > 0) {
                  tableParts.push(item.table_caption.join('\n'))
                }
                if (item.table_body) {
                  // 将第一行的<td>转换为<th>，使其成为表头
                  let tableBody = item.table_body
                  // 匹配第一个<tr>标签及其内容，将其中的<td>替换为<th>
                  tableBody = tableBody.replace(
                    /<tr>([\s\S]*?)<\/tr>/,
                    (match, rowContent) => {
                      // 将第一行中的所有<td>替换为<th>
                      const headerRow = rowContent.replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>')
                      return `<tr>${headerRow}</tr>`
                    }
                  )
                  tableParts.push(tableBody)
                }
                if (item.table_footnote && Array.isArray(item.table_footnote) && item.table_footnote.length > 0) {
                  tableParts.push(...item.table_footnote.map(fn => `*${fn}*`))
                }
                content = tableParts.join('\n\n')
                break
              
              case 'formula':
                // formula类型：如果有formula_content或formula_latex，使用它们
                if (item.formula_content) {
                  content = `$$${item.formula_content}$$`
                } else if (item.formula_latex) {
                  content = `$$${item.formula_latex}$$`
                } else if (item.text) {
                  content = `$$${item.text}$$`
                }
                break
              
              case 'title':
              case 'header':
              case 'footer':
              case 'aside_text':
              case 'page_number':
                // 这些类型通常有text字段，如果没有则使用空字符串
                content = item.text || ''
                break
              
              default:
                // 其他类型：尝试使用text字段
                content = item.text || ''
            }
          }
          
          return {
            id: item.id ?? `${item.page_idx}-${idx}`,
            type: item.type,
            bbox: item.bbox,
            page_idx: item.page_idx,
            content,
            text: item.text,
            score: item.score,
            sub_type: item.sub_type,
          }
        })
        setItems(mapped)
        const allTypes = new Set<string>()
        mapped.forEach((m) => allTypes.add(m.type))
        setFilterTypes(allTypes)
      } catch (err) {
        setError((err as Error).message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [setFilterTypes])

  const filteredItems = useMemo(() => items.filter((i) => Array.isArray(i.bbox) && i.bbox.length === 4), [items])

  const sortedItems = useMemo(
    () => [...filteredItems].sort((a, b) => a.page_idx - b.page_idx || a.id.localeCompare(b.id)),
    [filteredItems],
  )

  // 选中时，让右侧选中区域居中
  useEffect(() => {
    if (!activeId) return
    const target = filteredItems.find((i) => i.id === activeId)
    if (!target) return

    suppressScrollSyncRef.current = true
    if (suppressTimerRef.current) {
      window.clearTimeout(suppressTimerRef.current)
    }

    // 找到 Markdown 块元素，让右侧选中区域居中
    const pageNumber = target.page_idx + 1
    const mdBlockEl = document.getElementById(`md-${activeId}`)
    const mdScroll = mdScrollRef.current

    if (mdBlockEl && mdScroll) {
      const containerRect = mdScroll.getBoundingClientRect()
      const mdRect = mdBlockEl.getBoundingClientRect()
      const mdCenter = mdRect.top + mdRect.height / 2 - containerRect.top + mdScroll.scrollTop
      const targetScroll = mdCenter - containerRect.height / 2

      mdScroll.scrollTo({
        top: Math.max(0, targetScroll),
        behavior: 'smooth',
      })
    }

    suppressTimerRef.current = window.setTimeout(() => {
      suppressScrollSyncRef.current = false
    }, 300)

    setCurrentPage(pageNumber)
  }, [activeId, filteredItems, setCurrentPage])

  // 计算当前视口中心所在的页数
  const getCurrentPageFromScroll = (scrollContainer: HTMLElement, isPdf: boolean): number | null => {
    const containerRect = scrollContainer.getBoundingClientRect()
    const viewportCenter = containerRect.top + containerRect.height / 2

    if (isPdf) {
      // 对于PDF，找到页面底部超过视口中线的页面
      const pages = document.querySelectorAll('.pdf-page')
      let targetPage: number | null = null
      
      // 从前往后查找，找到第一个底部超过中线的页面
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i] as HTMLElement
        const rect = page.getBoundingClientRect()
        // 如果页面底部超过视口中线，返回该页面
        if (rect.bottom > viewportCenter) {
          targetPage = i + 1
          break
        }
      }
      
      // 如果没找到（所有页面都在中线以上），找到最接近中线的页面
      if (targetPage === null) {
        let closestPage = 1
        let minDistance = Infinity
        for (let i = 0; i < pages.length; i++) {
          const page = pages[i] as HTMLElement
          const rect = page.getBoundingClientRect()
          // 计算页面中心到中线的距离
          const pageCenter = rect.top + rect.height / 2
          const distance = Math.abs(pageCenter - viewportCenter)
          if (distance < minDistance) {
            minDistance = distance
            closestPage = i + 1
          }
        }
        return closestPage
      }
      
      return targetPage
    } else {
      // 对于Markdown，找到视口中心所在的块
      type Closest = { id: string; distance: number; page: number }
      let closest: Closest | null = null

      sortedItems.forEach((item) => {
        const mdEl = document.getElementById(`md-${item.id}`)
        if (!mdEl) return

        const rect = mdEl.getBoundingClientRect()
        const blockCenter = rect.top + rect.height / 2
        const distance = Math.abs(blockCenter - viewportCenter)

        if (!closest || distance < closest.distance) {
          closest = { id: item.id, distance, page: item.page_idx + 1 }
        }
      })

      return closest ? closest.page : null
    }
  }

  // 同步另一侧的滚动到指定页数
  const syncScrollToPage = (targetPage: number, sourceIsPdf: boolean) => {
    // 对于PDF触发的同步，即使suppressScrollSyncRef为true也允许执行（用户主动滚动PDF）
    // 对于Markdown触发的同步，如果suppressScrollSyncRef为true则跳过（避免循环）
    if (!sourceIsPdf && suppressScrollSyncRef.current) return
    
    // 如果目标页面和上次同步的页面相同，跳过（避免重复触发）
    if (lastSyncedPageRef.current === targetPage && sourceIsPdf) {
      return
    }

    suppressScrollSyncRef.current = true
    if (suppressTimerRef.current) {
      window.clearTimeout(suppressTimerRef.current)
    }

    if (sourceIsPdf) {
      // PDF滚动，同步Markdown - 滚动到目标页面内容的顶部
      const mdScroll = mdScrollRef.current
      if (!mdScroll) {
        suppressScrollSyncRef.current = false
        return
      }

      // 找到目标页面的第一个块，然后找到它所属的页面组
      const targetItem = sortedItems.find((item) => item.page_idx + 1 === targetPage)
      if (!targetItem) {
        suppressScrollSyncRef.current = false
        return
      }

      const mdBlockEl = document.getElementById(`md-${targetItem.id}`)
      if (!mdBlockEl) {
        suppressScrollSyncRef.current = false
        return
      }

      // 找到该块所属的页面组（md-page-group）
      const pageGroupEl = mdBlockEl.closest('.md-page-group') as HTMLElement
      if (!pageGroupEl) {
        // 如果找不到页面组，回退到使用块本身
        const containerRect = mdScroll.getBoundingClientRect()
        const mdRect = mdBlockEl.getBoundingClientRect()
        const targetTop = mdRect.top - containerRect.top + mdScroll.scrollTop
        lastSyncedPageRef.current = targetPage
        mdScroll.scrollTop = Math.max(0, targetTop)
        return
      }

      // 计算页面组相对于滚动容器的位置
      const containerRect = mdScroll.getBoundingClientRect()
      const pageGroupRect = pageGroupEl.getBoundingClientRect()
      // 获取页面组相对于滚动容器的顶部位置
      const targetTop = pageGroupRect.top - containerRect.top + mdScroll.scrollTop

      // 记录同步的页码
      lastSyncedPageRef.current = targetPage

      mdScroll.scrollTop = Math.max(0, targetTop)
    } else {
      // Markdown滚动，同步PDF
      const pdfScroll = pdfScrollRef.current
      if (!pdfScroll) return

      const pdfPageEl = document.querySelector(`.pdf-page:nth-child(${targetPage})`) as HTMLElement
      if (!pdfPageEl) return

      const containerRect = pdfScroll.getBoundingClientRect()
      const pdfRect = pdfPageEl.getBoundingClientRect()
      const pdfCenter = pdfRect.top + pdfRect.height / 2 - containerRect.top + pdfScroll.scrollTop
      const targetScroll = pdfCenter - containerRect.height / 2

      pdfScroll.scrollTop = Math.max(0, targetScroll)
    }

    // 对于PDF触发的同步，延长抑制时间，确保Markdown滚动完成
    // 对于Markdown触发的同步，缩短抑制时间，避免影响PDF滚动检测
    const suppressTime = sourceIsPdf ? 500 : 200
    suppressTimerRef.current = window.setTimeout(() => {
      suppressScrollSyncRef.current = false
      // 如果是PDF触发的，在抑制期结束后清除页码记录，允许下次检测
      if (sourceIsPdf) {
        // 延迟清除，确保滚动完成
        setTimeout(() => {
          lastSyncedPageRef.current = null
        }, 100)
      }
    }, suppressTime)
  }

  // 处理PDF滚动
  const handlePdfScroll = debounce(() => {
    // PDF滚动时，即使suppressScrollSyncRef为true也要检测（因为可能是用户手动滚动PDF）
    // 但需要检查是否真的改变了页面
    const pdfScroll = pdfScrollRef.current
    if (!pdfScroll) return

    const currentPage = getCurrentPageFromScroll(pdfScroll, true)
    if (currentPage && currentPage !== lastSyncedPageRef.current) {
      // 只有在页面真正改变时才同步
      setCurrentPage(currentPage)
      syncScrollToPage(currentPage, true)
    }
  }, 100)

  // 处理Markdown滚动
  const handleMdScroll = debounce(() => {
    if (suppressScrollSyncRef.current) return
    const mdScroll = mdScrollRef.current
    if (!mdScroll) return

    const currentPage = getCurrentPageFromScroll(mdScroll, false)
    if (currentPage) {
      setCurrentPage(currentPage)
      syncScrollToPage(currentPage, false)
    }
  }, 150)

  useEffect(() => {
    const pdfEl = pdfScrollRef.current
    const mdEl = mdScrollRef.current
    if (!pdfEl || !mdEl) return

    pdfEl.addEventListener('scroll', handlePdfScroll)
    mdEl.addEventListener('scroll', handleMdScroll)

    return () => {
      pdfEl.removeEventListener('scroll', handlePdfScroll)
      mdEl.removeEventListener('scroll', handleMdScroll)
      if (suppressTimerRef.current) window.clearTimeout(suppressTimerRef.current)
    }
  }, [handlePdfScroll, handleMdScroll])

  if (loading) return <div className="page">加载中...</div>
  if (error) return <div className="page error">加载失败: {error}</div>

  return (
    <div className="page">
      <header className="header">
        <h1>PDF + Markdown 双向联动演示</h1>
        <Toolbar items={filteredItems} onSave={() => alert('保存功能可在此扩展')} />
      </header>
      <div className="content-shell">
        <div className="file-column-placeholder" />
        <div className="main-pane">
          <SplitPane
            left={
              <div className="scroll-container" ref={pdfScrollRef}>
                <PdfViewer items={filteredItems} config={config} />
              </div>
            }
            right={
              <div className="scroll-container" ref={mdScrollRef}>
                <MarkdownPanel items={filteredItems} imageBase={config.imageBase} />
              </div>
            }
          />
        </div>
      </div>
    </div>
  )
}

export default App
