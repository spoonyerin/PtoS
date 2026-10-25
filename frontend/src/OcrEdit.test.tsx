import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const fixture = vi.hoisted(() => ({ text: '은행입니다. 인증번호를 알려주세요. https://example.invalid/original', urls: [], warnings: [], engine: 'tesseract-5', ocr_confidence: null }))
// OCR만 가짜로 제공하고 실제 App → ScreenshotInput → useAnalysis 상태 연결을 검증한다.
vi.mock('./hooks/useOcr', () => ({
  useOcr: () => ({ result: fixture, loading: false, error: null, reset: vi.fn(), submit: vi.fn() }),
  useOcrReview: () => ({ ready: true, urls: [], loading: false, error: null, retry: vi.fn() }),
}))

test.each(['새 문자 내용', '은행입니다. 인증번호를 알려주세요. https://example.invalid/changed'])('OCR 편집 이벤트 직후 확인과 이전 분석을 즉시 해제한다: %s', async edited => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71', risk_level: 'dangerous', confidence: null,
    risk_factors: [], evidence: [], explanation: '이전 분석의 설명입니다.', action_guidance: ['이전 안내'], limitations: [],
    analysis_version: 'rules-dev-v2', analysis_mode: 'rules', is_demo: false, policy_reason: 'COMBINED_IDENTITY_REQUEST',
    urls: [], input_assessment: { status: 'action_identified', reasons: [] }, analysis_stages: [],
  })))
  vi.stubGlobal('fetch', fetch)
  render(<App />)
  await userEvent.click(screen.getByRole('radio', { name: '스크린샷' }))
  await userEvent.click(screen.getByRole('checkbox'))
  await userEvent.click(screen.getByRole('button', { name: '확인한 내용으로 분석하기' }))
  await screen.findByRole('heading', { name: /^위험$/ })
  expect(screen.getByRole('checkbox')).toBeChecked()
  expect(screen.getByText('이전 분석의 설명입니다.')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: edited } })
  // await/waitFor/URL 후보 응답 없이 같은 편집 이벤트 직후 검사한다.
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  expect(screen.getByRole('button', { name: '확인한 내용으로 분석하기' })).toBeDisabled()
  expect(screen.queryByRole('heading', { name: /^위험$/ })).not.toBeInTheDocument()
  expect(screen.queryByText('이전 분석의 설명입니다.')).not.toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(1)
})
