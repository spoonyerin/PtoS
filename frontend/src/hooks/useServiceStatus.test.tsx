import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { LLM_REVIEW_NOTICE } from '../components/LlmReviewNotice'
import { ServiceStatusProvider } from './useServiceStatus'

const NOTICE = 'URL 확인 기능이 켜져 있어요. 주소를 그대로 보내지 않고, 주소에서 만든 일부 정보(해시)만 Google로 전송돼요.'

beforeEach(() => {
  history.replaceState(null, '', '/#text')
  vi.stubGlobal('scrollTo', vi.fn())
})

// 새 화면에는 입력 방식 라디오가 없다. 홈 메뉴로 다른 확인 화면에 들어간다.
async function openPage(name: '링크 확인하기' | '사진으로 확인하기') {
  await userEvent.click(screen.getByRole('button', { name: '홈으로 돌아가기' }))
  await userEvent.click(screen.getByRole('button', { name }))
}

function renderWith(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  return render(<ServiceStatusProvider><App /></ServiceStatusProvider>)
}

function ready(url_reputation: unknown, llm_review: unknown = 'off') {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ready', mode: 'rules', url_reputation, llm_review })))
}

test('켜짐이면 문자·URL 입력 화면에 전송 안내를 보인다', async () => {
  const fetchMock = ready('live')
  renderWith(fetchMock)
  await screen.findByText(/URL 평판 조회\(Google Safe Browsing\)는 켜져 있지만/)
  expect(screen.getByRole('note')).toHaveTextContent(NOTICE)
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/ready', expect.objectContaining({ cache: 'no-store' }))
  await openPage('링크 확인하기')
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
  // 확인에 실패하면 두 안내(주소 해시 전송, 추가 검토 전송)를 모두 보인다.
  expect(screen.getByText(NOTICE)).toBeInTheDocument()
  expect(screen.getByText(LLM_REVIEW_NOTICE)).toBeInTheDocument()
  expect(screen.getByText(/URL 평판 조회가 켜져 있는지 확인하지 못했으며/)).toBeInTheDocument()
})

test('스크린샷 업로드 화면에는 전송 안내가 없다', async () => {
  renderWith(ready('live'))
  await screen.findByText(/켜져 있지만/)
  await openPage('사진으로 확인하기')
  expect(screen.queryByRole('note')).toBeNull()
})

test.each([
  ['live', /URL 평판 조회\(Google Safe Browsing\)는 켜져 있지만/],
  ['off', /URL 평판 조회는 꺼져 있으며/],
])('홈 하단 안내는 서버 상태(%s)에 맞춰 바뀌고 고정된 미연결 문구가 없다', async (status, expected) => {
  history.replaceState(null, '', '/')
  renderWith(ready(status))
  await screen.findByText(expected)
  expect(screen.queryByText(/아직 연결되지 않았어요/)).toBeNull()
})

test('추가 검토가 켜져 있으면 문자 입력 화면에 가린 문장 전송 안내를 보인다', async () => {
  renderWith(ready('off', 'live'))
  await screen.findByText(/URL 평판 조회는 꺼져 있으며/)
  expect(screen.getByRole('note')).toHaveTextContent(LLM_REVIEW_NOTICE)
  expect(screen.queryByText(NOTICE)).toBeNull()
})

test('추가 검토가 꺼져 있다고 확인되면 그 안내를 숨긴다', async () => {
  renderWith(ready('live', 'off'))
  await screen.findByText(/켜져 있지만/)
  expect(screen.queryByText(LLM_REVIEW_NOTICE)).toBeNull()
  expect(screen.getByRole('note')).toHaveTextContent(NOTICE)
})

test('준비 응답에 추가 검토 상태가 없으면 확인 실패로 보고 두 안내를 모두 보인다', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ready', mode: 'rules', url_reputation: 'off' })))
  renderWith(fetchMock)
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(await screen.findByText(LLM_REVIEW_NOTICE)).toBeInTheDocument()
  expect(screen.getByText(NOTICE)).toBeInTheDocument()
})
