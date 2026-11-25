import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { codespacesServerOptions } from './codespaces.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      ...codespacesServerOptions(env),
      proxy: { '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
    },
    // 발표 예비(노트북 + 터널, docs/DEPLOY_ORACLE.md 10절): 빌드 결과를 띄우고 터널의 정확한 호스트 하나만 허용한다.
    preview: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
      ...(env.PTOS_TUNNEL_HOST ? { allowedHosts: [env.PTOS_TUNNEL_HOST] } : {}),
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
    },
  }
})
