export type ContentType = 'text' | 'title' | 'table' | 'image' | 'formula' | 'header' | 'footer' | string

export interface ContentItem {
  id: string
  type: ContentType
  bbox: [number, number, number, number]
  page_idx: number
  content?: string
  text?: string
  score?: number
  sub_type?: string
}

export interface ViewerConfig {
  pdfUrl: string
  contentListUrl: string
  markdownUrl?: string
  imageBase: string
  bboxNormalizedTo?: number // e.g. 1000 if 0-1000 归一化
}

