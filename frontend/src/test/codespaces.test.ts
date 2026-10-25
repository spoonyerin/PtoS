import { codespacesServerOptions } from '../../codespaces'

test('로컬 실행에는 Codespaces 호스트나 HMR을 지정하지 않는다', () => {
  expect(codespacesServerOptions({})).toEqual({})
  expect(codespacesServerOptions({ CODESPACE_NAME: 'unused' })).toEqual({})
})

test('Codespaces에서는 해당 환경의 5173 호스트 하나와 HTTPS용 HMR을 설정한다', () => {
  expect(codespacesServerOptions({
    CODESPACES: 'true', CODESPACE_NAME: 'ptos-example',
    GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev',
  })).toEqual({
    allowedHosts: ['ptos-example-5173.app.github.dev'],
    hmr: { host: 'ptos-example-5173.app.github.dev', protocol: 'wss', clientPort: 443 },
  })
})

test('전달 도메인을 하드코딩하지 않는다', () => {
  expect(codespacesServerOptions({
    CODESPACES: 'true', CODESPACE_NAME: 'ptos-example',
    GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'alternate.example.com',
  }).allowedHosts).toEqual(['ptos-example-5173.alternate.example.com'])
})

test.each([
  { CODESPACES: 'true' },
  { CODESPACES: 'true', CODESPACE_NAME: 'ptos-example' },
  { CODESPACES: 'true', GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev' },
])('Codespaces 설정이 빠진 경우 시작 원인을 명시한다', env => {
  expect(() => codespacesServerOptions(env)).toThrow('CODESPACE_NAME')
})
