import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return

          if (id.includes('echarts')) return 'vendor-echarts'
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element-plus'
          if (id.includes('vue-router')) return 'vendor-router'
          if (id.includes('pinia')) return 'vendor-pinia'
          if (id.includes('axios')) return 'vendor-axios'
          if (id.includes('lodash')) return 'vendor-lodash'
          if (id.includes('dayjs')) return 'vendor-dayjs'
          
          // 其他第三方库单独分包，避免单个chunk过大
          const match = id.match(/node_modules\/(@[^/]+\/[^/]+|[^/]+)/)
          if (match) {
            const moduleName = match[1]
            // 只将知名的大型库单独分包，其他的保持默认行为
            if (['vue', 'moment', 'underscore', 'rxjs', 'd3'].some(lib => moduleName.includes(lib))) {
              return `vendor-${moduleName.replace(/@/, '').replace(/\//, '-')}`
            }
          }
          
          // 不设置默认返回值，让Rollup自动处理
        },
      },
    },
    chunkSizeWarningLimit: 1000, // 提高警告阈值到1000KB
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
