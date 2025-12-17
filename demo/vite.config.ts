import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 代理所有对 spotlight.shanghai-9.zos.ctyun.cn 的请求
      '/api/proxy/spotlight': {
        target: 'https://spotlight.shanghai-9.zos.ctyun.cn',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/proxy\/spotlight/, ''),
      },
    },
  },
})
