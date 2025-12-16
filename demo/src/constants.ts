import type { ContentType } from './types'

export const TYPE_COLORS: Record<ContentType, string> = {
  text: '#3b82f6',
  title: '#2563eb',
  table: '#22c55e',
  image: '#f97316',
  formula: '#a855f7',
  header: '#0ea5e9',
  footer: '#0ea5e9',
}

export const LOW_CONF_THRESHOLD = 0.6

