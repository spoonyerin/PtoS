import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { codespacesServerOptions } from './codespaces.ts'

// 발표 서버(deploy/oracle/Caddyfile)와 같은 보안 헤더. 두 곳을 함께 고친다.
const PTOS_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"

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
      headers: {
        'Content-Security-Policy': PTOS_CSP,
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY',
      },
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
