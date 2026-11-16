beforeEach(() => {
  history.replaceState(null, '', '/#text')
  vi.stubGlobal('scrollTo', vi.fn())
})
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { UrlFinding } from './api/types'

function ruleResponse() {
  return {
    request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71',
    risk_level: 'dangerous',
    confidence: null,
    risk_factors: ['인증번호·개인정보 요구'],
    explanation: '인증번호 요구를 확인했어요.',
    action_guidance: ['인증번호를 알려주지 마세요.'],
    limitations: ['모델과 URL 평판 조회는 아직 없어요.'],
    analysis_version: 'rules-dev-v2',
    is_demo: false,
    analysis_mode: 'rules',
    policy_reason: 'COMBINED_IDENTITY_REQUEST',
    urls: [] as UrlFinding[],
    evidence: [
      {
        factor_code: 'CREDENTIAL_REQUEST',
        label: '인증번호·개인정보 요구',
        source: 'rule',
        rule_id: 'credential_request-v1',
        snippet: '인증번호를 알려주세요',
        start: 7,
        end: 18,
      },
    ],
    input_assessment: {
      status: 'action_identified',
      reasons: ['요구 표현이 있어요.'],
    },
    analysis_stages: [
      { name: 'rules', status: 'completed' },
      { name: 'lightweight_model', status: 'not_implemented' },
      { name: 'url_reputation', status: 'not_applicable' },
    ],
  }
}

test('빈 입력은 서버로 보내지 않고 안내한다', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(screen.getByRole('alert')).toHaveTextContent(
    '문자 내용을 입력해주세요.',
  )
  expect(screen.getByRole('textbox', { name: '문자 내용' })).toHaveFocus()
  expect(fetchMock).not.toHaveBeenCalled()
})

test('일반 분석 화면에는 결과 선택이 없고 개발 제한을 표시한다', () => {
  render(<App />)
  expect(screen.queryAllByRole('radio')).toHaveLength(0)
  expect(screen.queryByRole('radio', { name: '위험' })).not.toBeInTheDocument()
  expect(screen.getByText(/규칙 기반 개발 버전/)).toBeInTheDocument()
  // 상태 제공자 없이 그리면 확인하지 못한 상태다. 켜져 있을 수 있으므로 전송 안내를 보인다.
  expect(screen.getByText(/URL 평판 조회가 켜져 있는지 확인하지 못했으며/)).toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent('주소에서 만든 일부 정보(해시)만 Google로 전송돼요.')
})

test('문자만 전송하고 근거를 표시한다. 다시 수정하면 이전 결과를 지운다', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(ruleResponse())))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  const text = screen.getByRole('textbox', { name: '문자 내용' })
  fireEvent.change(text, { target: { value: '<script>수정한 문자</script>' } })
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  await screen.findByRole('heading', { name: '위험' })
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    input_type: 'text',
    content: '<script>수정한 문자</script>',
  })
  expect(screen.getByText('인증번호 요구를 확인했어요.')).toBeInTheDocument()
  expect(screen.getByText('인증번호를 알려주세요')).toBeInTheDocument()
  expect(screen.getByText('규칙 기반 개발 버전')).toBeInTheDocument()
  fireEvent.change(text, { target: { value: '새 문자' } })
  expect(
    screen.queryByText('인증번호 요구를 확인했어요.'),
  ).not.toBeInTheDocument()
})

test('같은 순간의 중복 제출을 막고 완료 후 다시 제출할 수 있다', async () => {
  let resolve!: (value: Response) => void
  const fetchMock = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((r) => {
        resolve = r
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: '은행입니다. 인증번호를 알려주세요.' },
  })
  const button = screen.getByRole('button', { name: '분석하기' })
  const form = button.closest('form')!
  fireEvent.submit(form)
  fireEvent.submit(form)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(button).toBeDisabled()
  expect(screen.getByRole('textbox')).toBeDisabled()
  resolve(new Response(JSON.stringify(ruleResponse())))
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.submit(form)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('서버 오류 후 입력을 유지하고 재시도한다', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response('private stack trace', { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(ruleResponse())))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: '은행입니다. 인증번호를 알려주세요.' },
  })
  const content = (screen.getByRole('textbox') as HTMLTextAreaElement).value
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '서버에서 분석을 완료하지 못했어요.',
  )
  expect(screen.getByRole('textbox')).toHaveValue(content)
  expect(screen.queryByText('private stack trace')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(
    await screen.findByRole('heading', { name: '위험' }),
  ).toBeInTheDocument()
})

test('너무 긴 입력은 잘라 보내지 않고 수정 안내한다', () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: '😀'.repeat(10_001) },
  })
  fireEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(screen.getByRole('alert')).toHaveTextContent('10,000자 이하')
  expect(fetchMock).not.toHaveBeenCalled()
})

test('근거의 HTML 형태 문자열을 이미지나 링크로 해석하지 않는다', async () => {
  const response = ruleResponse()
  response.evidence[0].snippet =
    '인증번호 <img src=x onerror=alert(1)> 알려주세요'
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(response))),
  )
  render(<App />)
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: '확인할 문자' },
  })
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(
    await screen.findByText(response.evidence[0].snippet),
  ).toBeInTheDocument()
  expect(document.querySelector('.source-evidence img')).toBeNull()
  expect(document.querySelector('.result-card a')).toBeNull()
})

test('URL 직접 입력을 전송하고 주소와 미연결 상태를 링크 없이 표시한다', async () => {
  const url = 'https://예시.한국/공지'
  const body = ruleResponse()
  body.risk_level = 'insufficient_information'
  body.input_assessment.status = 'url_only'
  body.policy_reason = 'ANALYSIS_INCOMPLETE'
  body.explanation = 'URL의 형식만 확인했어요.'
  body.action_guidance = ['원래 문자와 요청 출처를 확인해주세요.']
  body.analysis_stages[2].status = 'not_connected'
  body.risk_factors = []
  body.evidence = []
  body.urls = [
    {
      original_url: url,
      normalized_url: 'https://xn--vv4b11d.xn--3e0b707e/%EA%B3%B5%EC%A7%80',
      ascii_host: 'xn--vv4b11d.xn--3e0b707e',
      validation_status: 'valid',
      validation_message: '주소 형식만 확인했어요.',
      warnings: [],
      occurrences: [{ text: url, start: 0, end: Array.from(url).length }],
      reputation: {
        status: 'not_connected',
        provider: null,
        checked_at: null,
        full_hash_verified: false,
        cache_hit: false,
      },
    },
  ]
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body)))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: '홈으로 돌아가기' }))
  await userEvent.click(screen.getByRole('button', { name: '링크 확인하기' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'URL 주소' }), {
    target: { value: url },
  })
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  await screen.findByRole('heading', { name: '정보 부족' })
  await userEvent.click(screen.getByText('분석 근거와 행동 안내 자세히 보기'))
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    input_type: 'url',
    content: url,
  })
  expect(
    screen.getByRole('region', { name: 'URL 형식 및 평판' }),
  ).toHaveTextContent('평판 조회 미연결')
  expect(
    within(screen.getByRole('region', { name: 'URL 형식 및 평판' })).getByText(
      url,
    ),
  ).toBeInTheDocument()
  expect(document.querySelector('.result-card a')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '다시 확인하기' }))
  await userEvent.click(screen.getByRole('button', { name: '홈으로 돌아가기' }))
  await userEvent.click(screen.getByRole('button', { name: '문자 확인하기' }))
  expect(
    screen.queryByRole('heading', { name: '정보 부족' }),
  ).not.toBeInTheDocument()
})

test('빈 URL은 전송하지 않고 주소 입력을 안내한다', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: '홈으로 돌아가기' }))
  await userEvent.click(screen.getByRole('button', { name: '링크 확인하기' }))
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  expect(screen.getByRole('alert')).toHaveTextContent(
    'URL 주소를 입력해주세요.',
  )
  expect(fetchMock).not.toHaveBeenCalled()
})

const FALSE_FIXED_NOTE = /아직 연결되지 않았어요/

function stubDialog() {
  // jsdom에는 showModal/close가 없다. 열림 상태만 흉내 낸다.
  vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (this: HTMLDialogElement) { this.open = true })
  vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (this: HTMLDialogElement) { this.open = false })
}

beforeAll(() => {
  // 메서드가 없으면 spyOn을 쓸 수 없으므로 빈 구현을 먼저 둔다.
  HTMLDialogElement.prototype.showModal ??= function () {}
  HTMLDialogElement.prototype.close ??= function () {}
})

test('홈과 알림에는 고정된 "연결되지 않았어요" 문구 대신 상태에 맞는 안내를 보인다 (상태 미확인)', async () => {
  history.replaceState(null, '', '/')
  stubDialog()
  render(<App />)
  expect(screen.getByText(/URL 평판 조회가 켜져 있는지 확인하지 못했으며/)).toBeInTheDocument()
  expect(screen.queryByText(FALSE_FIXED_NOTE)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '알림' }))
  const dialog = screen.getByRole('dialog', { name: '알림' })
  expect(dialog).toHaveTextContent('URL 평판 조회가 켜져 있는지 확인하지 못했으며')
  expect(dialog).not.toHaveTextContent(FALSE_FIXED_NOTE)
})

test('가족에게 공유는 미리보기를 먼저 열고 추가 요청을 보내지 않는다', async () => {
  stubDialog()
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(ruleResponse())))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  fireEvent.change(screen.getByRole('textbox', { name: '문자 내용' }), { target: { value: '은행입니다. 인증번호를 알려주세요.' } })
  await userEvent.click(screen.getByRole('button', { name: '분석하기' }))
  await screen.findByRole('heading', { name: '위험' })
  await userEvent.click(screen.getByRole('button', { name: '가족에게 공유' }))
  expect(screen.getByRole('dialog', { name: '가족에게 공유하기' })).toBeVisible()
  expect((screen.getByRole('textbox', { name: '공유할 내용' }) as HTMLTextAreaElement).value).toContain('[PtoS 분석 결과 공유]')
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

test('뒤로/앞으로 이동으로 다른 확인 화면에 가면 이전 원문을 지운다', () => {
  render(<App />)
  fireEvent.change(screen.getByRole('textbox', { name: '문자 내용' }), { target: { value: '은행입니다. 인증번호를 알려주세요.' } })
  act(() => {
    history.pushState(null, '', '/#url')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  expect(screen.getByRole('textbox', { name: 'URL 주소' })).toHaveValue('')
})
