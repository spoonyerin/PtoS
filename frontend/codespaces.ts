// GitHub가 생성한 해당 Codespace의 호스트만 허용한다. 로컬에서는 추가하지 않는다.
export function codespacesServerOptions(env: Record<string, string | undefined>) {
  if (env.CODESPACES !== 'true') return {}
  const name = env.CODESPACE_NAME
  const domain = env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN
  if (!name || !domain) {
    throw new Error('Codespaces의 CODESPACE_NAME과 GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN이 필요합니다. Codespace 터미널에서 실행해주세요.')
  }
  const hostname = `${name}-5173.${domain}`
  return {
    allowedHosts: [hostname],
    hmr: { host: hostname, protocol: 'wss' as const, clientPort: 443 },
  }
}
