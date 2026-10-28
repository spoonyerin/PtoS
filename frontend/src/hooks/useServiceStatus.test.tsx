import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { ServiceStatusProvider } from './useServiceStatus'

const NOTICE = 'URL 확인 기능이 켜져 있어요. 주소를 그대로 보내지 않고, 주소에서 만든 일부 정보(해시)만 Google로 전송돼요.'

function renderWith(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  return render(<ServiceStatusProvider><App /></ServiceStatusProvider>)
}

function ready(url_reputation: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ready', mode: 'rules', url_reputation })))
}

test('켜짐이면 문자·URL 입력 화면에 전송 안내를 보인다', async () => {
  const fetchMock = ready('live')
  renderWith(fetchMock)
  await screen.findByText(/URL 평판 조회\(Google Safe Browsing\)는 켜져 있지만/)
  expect(screen.getByRole('note')).toHaveTextContent(NOTICE)
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/ready', expect.objectContaining({ cache: 'no-store' }))
  await userEvent.click(screen.getByRole('radio', { name: 'URL 직접 입력' }))
  expect(screen.getByRole('note')).toHaveTextContent(NOTICE)
})

test('꺼짐이 확인되면 안내를 숨긴다', async () => {
  renderWith(ready('off'))
  await screen.findByText(/URL 평판 조회는 꺼져 있으며/)
  expect(screen.queryByRole('note')).toBeNull()
  expect(screen.queryByText(NOTICE)).toBeNull()
})

test.each([
  ['연결 실패', vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))],
  ['HTTP 503', vi.fn().mockResolvedValue(new Response('{}', { status: 503 }))],
  ['알 수 없는 값', ready('maybe')],
  ['JSON 아님', vi.fn().mockResolvedValue(new Response('not json'))],
])('상태 확인 실패(%s)면 켜져 있을 수 있으므로 안내를 보인다', async (_name, fetchMock) => {
  renderWith(fetchMock)
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(screen.getByRole('note')).toHaveTextContent(NOTICE)
  expect(screen.getByText(/URL 평판 조회가 켜져 있는지 확인하지 못했으며/)).toBeInTheDocument()
})

test('스크린샷 업로드 화면에는 전송 안내가 없다', async () => {
  renderWith(ready('live'))
  await screen.findByText(/켜져 있지만/)
  await userEvent.click(screen.getByRole('radio', { name: '스크린샷' }))
  expect(screen.queryByRole('note')).toBeNull()
})
