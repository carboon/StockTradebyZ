import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

function getPackageChunkName(id: string): string | null {
  if (!id.includes('node_modules')) return null

  const normalized = id.split('node_modules/').pop()
  if (!normalized) return 'vendor'

  const segments = normalized.split('/')
  const packageName = segments[0] === '.pnpm'
    ? segments[1]?.split('@').slice(0, -1).join('@') || 'vendor'
    : segments[0]?.startsWith('@')
      ? `${segments[0]}/${segments[1]}`
      : segments[0]

  return packageName
    .replace(/^@/, '')
    .replace(/[\\/]/g, '-')
    .replace(/[^a-zA-Z0-9-_]/g, '-')
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  const wsProxyTarget = apiProxyTarget.replace(/^http/i, 'ws')

  return {
    plugins: [vue()],
    css: {
      preprocessorOptions: {
        scss: {
          api: 'modern-compiler',
        },
      },
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    build: {
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return

            const packageName = getPackageChunkName(id)
            if (!packageName) return

            if (packageName.startsWith('element-plus')) return `vendor-element-plus-${packageName}`
            if (packageName.startsWith('lodash-unified')) return 'vendor-element-plus-element-plus'
            if (packageName.startsWith('echarts') || packageName.startsWith('zrender')) return `vendor-echarts-${packageName}`
            if (packageName.startsWith('vue') || packageName.startsWith('pinia')) return 'vendor-vue-core'
            if (packageName.startsWith('axios')) return `vendor-axios-${packageName}`

            return `vendor-${packageName}`
          },
        },
      },
    },
    server: {
      port: 5173,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: wsProxyTarget,
          ws: true,
        },
      },
    },
  }
})
