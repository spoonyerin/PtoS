import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { familyApi } from '../api/family'
import { parseFamilyRoute } from '../components/family/FamilyPages'
import { factorCodes } from '../components/family/FamilySendSheet'
import { FamilyProvider } from '../hooks/useFamily'
import { ServiceStatusProvider } from '../hooks/useServiceStatus'
import { readDeviceToken, saveDeviceToken } from './deviceToken'
import { shareFixture } from '../test/shareFixture'

const summary = (overrides = {}) => ({
  premium: false, auto_alert: { enabled: false, link_id: null }, links: [], push_subscribed: false,
  waiting_requests: 0, new_replies: 0, server_time: '2026-11-25T01:00:00+00:00', ...overrides,
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => localStorage.clear())

test('가족 화면 주소를 해석한다', () => {
  expect(parseFamilyRoute('#text')).toBeNull()
  expect(parseFamilyRoute('#family')).toEqual({ name: 'protect' })
  expect(parseFamilyRoute('#family/records/received')).toEqual({ name: 'records', box: 'received' })
  expect(parseFamilyRoute('#family/records')).toEqual({ name: 'records', box: 'sent' })
  expect(parseFamilyRoute('#family/request/abc')).toEqual({ name: 'request', id: 'abc' })
  expect(parseFamilyRoute('#family/invite/tok%2B')).toEqual({ name: 'invite', token: 'tok+' })
})

test('확인 요청에는 위험 요소 코드만 넣고 원문·URL은 넣지 않는다', async () => {
  saveDeviceToken('device-token-123456')
  const fetchMock = vi.fn().mockResolvedValue(json({ request_ids: ['r1'] }, 201))
  vi.stubGlobal('fetch', fetchMock)
  const result = shareFixture()
  await familyApi.sendRequests({ link_ids: ['l1'], risk_level: result.risk_level, factor_codes: factorCodes(result) })
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/v1/family/requests')
  expect(init.headers.Authorization).toBe('Bearer device-token-123456')
  const body = JSON.parse(init.body)
  expect(Object.keys(body).sort()).toEqual(['factor_codes', 'link_ids', 'risk_level'])
  for (const item of result.evidence) expect(init.body).not.toContain(item.snippet)
  for (const url of result.urls) expect(init.body).not.toContain(url.original_url)
})

test('서버가 기기를 모르면 저장한 기기 열쇠를 지운다', async () => {
  saveDeviceToken('device-token-123456')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ error: { code: 'DEVICE_REQUIRED', message: 'x', retryable: false } }, 401)))
  await expect(familyApi.summary()).rejects.toMatchObject({ code: 'DEVICE_REQUIRED' })
  expect(readDeviceToken()).toBeNull()
})

function renderApp(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  return render(<ServiceStatusProvider><FamilyProvider><App /></FamilyProvider></ServiceStatusProvider>)
}

function server(handlers: Record<string, (init?: RequestInit) => Response>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    if (url === '/api/v1/health/ready') {
      return json({ status: 'ready', mode: 'rules', url_reputation: 'off', llm_review: 'off', family: 'live', push: 'off' })
    }
    const handler = handlers[key]
    if (!handler) throw new Error(`unexpected ${key}`)
    return handler(init)
  })
}

test('가족 보호가 꺼진 서버에서는 홈에 가족 보호 카드가 없고 요청도 보내지 않는다', async () => {
  history.replaceState(null, '', '/')
  const fetchMock = vi.fn().mockResolvedValue(json({ status: 'ready', mode: 'rules', url_reputation: 'off', llm_review: 'off' }))
  renderApp(fetchMock)
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(screen.queryByRole('button', { name: /가족 보호/ })).toBeNull()
  expect(fetchMock.mock.calls.every(([url]) => url === '/api/v1/health/ready')).toBe(true)
  expect(readDeviceToken()).toBeNull()
})

test('홈의 가족 보호 카드에서 시연용 프리미엄을 시작하고 가족 연결 화면으로 간다', async () => {
  history.replaceState(null, '', '/')
  const fetchMock = server({
    'POST /api/v1/family/devices': () => json({ device_token: 'device-token-abcdefgh' }, 201),
    'PUT /api/v1/family/premium': () => json(summary({ premium: true })),
    'GET /api/v1/family/me': () => json(summary({ premium: true })),
  })
  renderApp(fetchMock)
  const tile = await screen.findByRole('button', { name: /가족 보호.*프리미엄 이용권/ })
  // 가족 보호를 쓰기 전에는 기기를 등록하지 않는다.
  expect(readDeviceToken()).toBeNull()
  await userEvent.click(tile)
  expect(await screen.findByRole('heading', { name: '가족 보호 프리미엄' })).toBeInTheDocument()
  expect(screen.getByText('시연용 · 실제 결제 없음')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '프리미엄 시작하기 (시연용)' }))
  expect(await screen.findByText('프리미엄이 시작됐어요!')).toBeInTheDocument()
  expect(readDeviceToken()).toBe('device-token-abcdefgh')
  await userEvent.click(screen.getByRole('button', { name: '지금 가족 연결하기' }))
  expect(await screen.findByRole('heading', { name: '가족 연결하기' })).toBeInTheDocument()
  expect(location.hash).toBe('#family/connect')
})

test('받은 확인 요청에 의견을 보내고, 원문 없이 위험 단계와 위험 요소만 보인다', async () => {
  saveDeviceToken('device-token-123456')
  history.replaceState(null, '', '/#family/request/r1')
  const item = {
    id: 'r1', box: 'received', name: '엄마', risk_level: 'dangerous', factor_codes: ['LINK_CLICK'], auto: false,
    created_at: '2026-11-25T01:00:00+00:00', expires_at: '2026-12-02T01:00:00+00:00', viewed_at: '2026-11-25T01:01:00+00:00', reply: null,
  }
  let sentBody = ''
  const fetchMock = server({
    'GET /api/v1/family/me': () => json(summary({ links: [{ id: 'l1', role: 'protected', name: '엄마', relation: null, status: 'connected', invite_expires_at: null }] })),
    'GET /api/v1/family/requests/r1': () => json(item),
    'POST /api/v1/family/requests/r1/reply': init => {
      sentBody = String(init?.body)
      return json({ ...item, reply: { choice: 'custom', text: '전화할게요', replied_at: '2026-11-25T01:02:00+00:00' } })
    },
  })
  renderApp(fetchMock)
  expect(await screen.findByText((_, node) => node?.tagName === 'SPAN' && node.textContent === '엄마 님이 확인을 요청했어요.')).toBeInTheDocument()
  expect(screen.getByText('링크 클릭·접속 요구')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '위험 단계' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('radio', { name: '직접 입력하기' }))
  await userEvent.type(screen.getByRole('textbox', { name: '보낼 메시지' }), '전화할게요')
  await userEvent.click(screen.getByRole('button', { name: '의견 보내기' }))
  expect(await screen.findByText('보낸 의견')).toBeInTheDocument()
  expect(JSON.parse(sentBody)).toEqual({ choice: 'custom', text: '전화할게요' })
})
