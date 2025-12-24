import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import type { ViewerConfig, ContentItem } from './types'
import { PdfViewer } from './components/PdfViewer'
import { MarkdownPanel } from './components/MarkdownPanel'
import { SplitPane } from './components/SplitPane'
import { useViewerStore } from './store'
import debounce from 'lodash.debounce'

type TaskAssets = {
  pdf_url: string
  content_list_url: string
  full_md_link: string
}

const DEFAULT_TASK_ASSETS: TaskAssets = {
  pdf_url:
    'https://spotlight.shanghai-9.zos.ctyun.cn/tasks/6df20a4f-32c3-4771-bb72-0c191a0533e5/vlm/Stabilizing Reinforcement Learning with LLMs-Formulation and Practices - 副本_13_origin.pdf',
  content_list_url:
    'https://spotlight.shanghai-9.zos.ctyun.cn/tasks/6df20a4f-32c3-4771-bb72-0c191a0533e5/vlm/Stabilizing Reinforcement Learning with LLMs-Formulation and Practices - 副本_13_content_list.json',
  full_md_link:
    'https://spotlight.shanghai-9.zos.ctyun.cn/tasks/6df20a4f-32c3-4771-bb72-0c191a0533e5/vlm/Stabilizing Reinforcement Learning with LLMs-Formulation and Practices - 副本_13.md',
}

// 将绝对地址转换为 Vite 代理地址，避免 CORS。保持路径编码。
const toProxyUrl = (url: string) => {
  const prefix = 'https://spotlight.shanghai-9.zos.ctyun.cn/'
  const trimmed = url.startsWith(prefix) ? url.slice(prefix.length) : url
  return `/api/proxy/spotlight/${encodeURI(trimmed)}`
}

const buildViewerConfig = (assets: TaskAssets): ViewerConfig => {
  // 从 content_list_url 推断 images 目录
  const imageBaseFromContentList = assets.content_list_url
    .replace('_content_list.json', '')
    .replace(/\/[^/]*$/, '/images')

  return {
    // 优先走代理，必要时在加载逻辑里回退直连
    pdfUrl: toProxyUrl(assets.pdf_url),
    contentListUrl: toProxyUrl(assets.content_list_url),
    markdownUrl: toProxyUrl(assets.full_md_link),
    imageBase: toProxyUrl(imageBaseFromContentList),
    bboxNormalizedTo: 1000,
  }
}

function App() {
  const [taskIdInput, setTaskIdInput] = useState(
    '6df20a4f-32c3-4771-bb72-0c191a0533e5', // 默认示例，方便调试
  )
  const [config, setConfig] = useState<ViewerConfig>(() => buildViewerConfig(DEFAULT_TASK_ASSETS))
  const [fileInfo, setFileInfo] = useState<{ type: string; sizeText?: string }>(() => {
    const parts = DEFAULT_TASK_ASSETS.pdf_url.split('.')
    const ext = parts[parts.length - 1]?.toLowerCase() ?? ''
    const type = ext === 'pdf' ? 'PDF' : ext.toUpperCase() || '文件'
    return { type }
  })
  const [fileName, setFileName] = useState<string>(() => {
    const parts = DEFAULT_TASK_ASSETS.pdf_url.split('/')
    return decodeURIComponent(parts[parts.length - 1] || '')
  })
  const [items, setItems] = useState<ContentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { activeId, setCurrentPage, setFilterTypes } = useViewerStore()
  const pdfScrollRef = useRef<HTMLDivElement>(null)
  const mdScrollRef = useRef<HTMLDivElement>(null)
  const suppressScrollSyncRef = useRef(false)
  const suppressTimerRef = useRef<number | null>(null)
  const lastSyncedPageRef = useRef<number | null>(null)

  const loadContentList = async (viewerConfig: ViewerConfig, rawAssets: TaskAssets) => {
    let lastError: Error | null = null
    // 先尝试代理，再回退直连
    const urlsToTry = [viewerConfig.contentListUrl, encodeURI(rawAssets.content_list_url)]

    for (const url of urlsToTry) {
      try {
        const res = await fetch(url)

        // 检查响应状态
        if (!res.ok) {
          throw new Error(`HTTP错误: ${res.status} ${res.statusText}\nURL: ${url}`)
        }

        const data = (await res.json()) as any[]
        const mapped: ContentItem[] = data.map((item, idx) => {
          // 后端有时会使用 "equation" 表示公式，这里统一归一到 "formula"
          let type = item.type === 'equation' ? 'formula' : item.type
          let content = item.content ?? item.text

          // 根据不同类型生成对应的markdown内容
          if (!content) {
            switch (type) {
              case 'image': {
                // image类型：使用img_path生成markdown图片引用，并在下方附上caption
                // 使用纯 markdown 文本，保留公式解析能力；样式在 CSS 中通过 img 后的第一个段落选择器控制
                if (item.img_path) {
                  const captions =
                    item.image_caption && Array.isArray(item.image_caption)
                      ? item.image_caption.join(' ')
                      : ''
                  content = captions
                    ? `![](${item.img_path})\n\n${captions}`
                    : `![](${item.img_path})`
                }
                break
              }

              case 'list':
                // list类型：将list_items数组转换为markdown列表
                if (item.list_items && Array.isArray(item.list_items)) {
                  // 转成标准 Markdown 列表：每项以 "- " 开头，保留可能存在的编号/符号
                  content = item.list_items
                    .map((raw: string) => raw.trim())
                    .filter((t: string) => t.length > 0)
                    .map((t: string) => {
                      // 如果已经是 markdown 列表前缀，则直接返回
                      if (/^([-*+]|\d+\.)\s+/.test(t)) {
                        return t
                      }
                      return `- ${t}`
                    })
                    .join('\n')
                }
                break

              case 'table': {
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
                    (_match: string, rowContent: string) => {
                      // 将第一行中的所有<td>替换为<th>
                      const headerRow = rowContent.replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>')
                      return `<tr>${headerRow}</tr>`
                    },
                  )
                  tableParts.push(tableBody)
                }
                if (item.table_footnote && Array.isArray(item.table_footnote) && item.table_footnote.length > 0) {
                  tableParts.push(...item.table_footnote.map((fn: string) => `*${fn}*`))
                }
                content = tableParts.join('\n\n')
                break
              }

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
            type,
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
        return
      } catch (err) {
        lastError = err as Error
        console.warn(`尝试 URL ${url} 失败:`, err)
        // 继续尝试下一个 URL
        continue
      }
    }

    // 所有 URL 都失败了
    const error = lastError || new Error('所有请求都失败了')
    let errorMessage = error.message || '未知错误'

    // 提供更详细的错误信息
    if (errorMessage === 'Failed to fetch' || errorMessage.includes('fetch')) {
      errorMessage = `网络请求失败: ${errorMessage}\n\n请求URL: ${viewerConfig.contentListUrl}\n\n可能的原因：\n1. CORS跨域问题 - 服务器未设置正确的CORS头\n2. 网络连接问题 - 请检查网络连接\n3. URL不正确 - 请检查URL是否正确\n4. 服务器未响应 - 请检查服务器状态`
    }

    console.error('加载数据失败:', error)
    setError(errorMessage)
  }

  const fetchTask = async () => {
    if (!taskIdInput.trim()) {
      setError('请输入有效的 task_id')
      return
    }

    setLoading(true)
    setError(null)
    setItems([])

    try {
      const resp = await fetch(
        `http://58.247.21.68:39020/api/v1/tasks/${encodeURIComponent(taskIdInput.trim())}`,
      )
      if (!resp.ok) {
        throw new Error(`获取任务信息失败: ${resp.status} ${resp.statusText}`)
      }
      const data = await resp.json()
      if (!data.success) {
        throw new Error(data.error_message || '任务查询失败')
      }
      if (!data.assets) {
        throw new Error('返回结果中缺少 assets 字段')
      }

      const nextAssets: TaskAssets = {
        pdf_url: data.assets.pdf_url,
        content_list_url: data.assets.content_list_url,
        full_md_link: data.assets.full_md_link,
      }
      const nextConfig = buildViewerConfig(nextAssets)

      setConfig(nextConfig)
      // 同步当前文件名，顶部展示
      const parts = nextAssets.pdf_url.split('/')
      setFileName(decodeURIComponent(parts[parts.length - 1] || ''))

      // 更新左侧文件信息（类型 + 大小）
      const nameParts = nextAssets.pdf_url.split('.')
      const ext = nameParts[nameParts.length - 1]?.toLowerCase() ?? ''
      const type = ext === 'pdf' ? 'PDF' : ext.toUpperCase() || '文件'
      let sizeText: string | undefined
      const sizeCandidate =
        data.assets.size ||
        data.assets.file_size ||
        data.assets.pdf_size ||
        data.assets.size_bytes ||
        data.assets.bytes
      if (typeof sizeCandidate === 'number' && sizeCandidate > 0) {
        const kb = sizeCandidate / 1024
        sizeText = kb >= 1024 ? `${(kb / 1024).toFixed(1)}MB` : `${kb.toFixed(1)}KB`
      }
      setFileInfo({ type, sizeText })

      await loadContentList(nextConfig, nextAssets)
    } catch (e) {
      const err = e as Error
      console.error('获取任务失败:', err)
      setError(err.message || '获取任务失败')
    } finally {
      setLoading(false)
    }
  }

  // 首次自动加载示例 task_id，避免页面空白
  useEffect(() => {
    // 只在首次挂载时触发一次
    fetchTask().catch((e) => {
      console.warn('初始任务加载失败:', e)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      // 对于Markdown，按页面分组元素（.md-page-group）来估算当前页，避免对每个内容块逐一测量，减少滚动时的布局计算开销
      const groups = scrollContainer.querySelectorAll<HTMLElement>('.md-page-group')
      if (!groups.length) return null

      // 先尝试找到第一个底部超过视口中线的页面组
      for (let i = 0; i < groups.length; i++) {
        const group = groups[i]
        const rect = group.getBoundingClientRect()
        if (rect.bottom > viewportCenter) {
          // pageIndices 与渲染顺序一致：第 i 个组对应第 i+1 页
          return i + 1
        }
      }

      // 如果所有页面组的底部都在中线以上，则选择中心最接近中线的页面组
      let closestPage = 1
      let minDistance = Infinity
      for (let i = 0; i < groups.length; i++) {
        const group = groups[i]
        const rect = group.getBoundingClientRect()
        const groupCenter = rect.top + rect.height / 2
        const distance = Math.abs(groupCenter - viewportCenter)
        if (distance < minDistance) {
          minDistance = distance
          closestPage = i + 1
        }
      }
      return closestPage
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
  if (error) {
    return (
      <div className="page error">
        <h2>加载失败</h2>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{error}</pre>
        <div style={{ marginTop: '20px' }}>
          <h3>可能的解决方案：</h3>
          <ul style={{ textAlign: 'left', display: 'inline-block' }}>
            <li>检查网络连接是否正常</li>
            <li>检查URL是否正确：<code>{config.contentListUrl}</code></li>
            <li>如果是CORS问题，需要在服务器端设置正确的CORS头，或使用代理</li>
            <li>检查浏览器控制台获取更多错误信息</li>
          </ul>
        </div>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="page">
        <header className="header">
          <div className="header-left">
            <span className="app-logo">MinerU</span>
            <h1 className="file-title" title={fileName}>
              {fileName || '原始文件'}
            </h1>
          </div>
          {/* 初始无数据时仍保留 task_id 输入与加载按钮，便于调试 */}
          <div className="task-input-row">
            <span>task_id：</span>
            <input
              className="task-input"
              value={taskIdInput}
              onChange={(e) => setTaskIdInput(e.target.value)}
              placeholder="请输入任务 ID"
            />
            <button onClick={fetchTask}>加载任务</button>
          </div>
        </header>
        <div style={{ marginTop: '40px' }}>请先输入 task_id 并点击「加载任务」。</div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="header">
        <div className="header-left">
          <span className="app-logo">聚光知识库</span>
          <h1 className="file-title" title={fileName}>
            {fileName || '原始文件'}
          </h1>
        </div>
      </header>
      <div className="content-shell">
        <aside className="file-column">
          <div className="file-column-header">文件</div>
          <div className="file-list">
            <div className="file-item file-item--active" title={fileName}>
              <div className="file-item-main">
                <div className="file-item-icon">{fileInfo.type.slice(0, 3)}</div>
                <div className="file-item-text">
                  <div className="file-item-title">{fileName || '当前文件'}</div>
                  <div className="file-item-meta">
                    {fileInfo.type}
                    {fileInfo.sizeText ? ` · ${fileInfo.sizeText}` : ''}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </aside>
        <div className="main-pane">
          <div className="pane-header">
            <div className="pane-header-tab pane-header-tab--active">原文件</div>
            <div className="pane-header-tab">Markdown</div>
          </div>
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
