import { render, screen, within } from '@testing-library/react'
import type { AnalysisResponse, UrlFinding } from '../api/types'
import { AnalysisResult } from './AnalysisResult'
import { GOOGLE_ADVISORY_URL } from './GoogleAdvisory'

const TEXT = '은행입니다. 인증번호를 알려주세요. https://example.invalid/test'
const URL_START = Array.from(TEXT).indexOf('h')
const URL_END = Array.from(TEXT).length

function result(provider: string | null, verified: boolean): AnalysisResponse {
  const url: UrlFinding = {
    original_url: 'https://example.invalid/test', normalized_url: 'https://example.invalid/test', ascii_host: 'example.invalid',
    validation_status: 'valid', validation_message: '형식만 확인했어요.', warnings: [],
    occurrences: [{ text: 'https://example.invalid/test', start: URL_START, end: URL_END }],
    reputation: { status: 'malicious', provider, checked_at: null, full_hash_verified: verified, threat_types: ['MALWARE'], cache_hit: false },
  }
  return {
    request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71', risk_level: 'dangerous', confidence: null,
    risk_factors: ['인증번호·개인정보 요구', 'URL 위협 목록의 전체 해시 일치'],
    explanation: '설명', action_guidance: ['안내'], limitations: [], analysis_version: 'rules-model-dev-v1',
    is_demo: false, analysis_mode: 'rules', policy_reason: 'VERIFIED_URL_THREAT_WITH_RULES',
    evidence: [
      { factor_code: 'CREDENTIAL_REQUEST', label: '인증번호·개인정보 요구', source: 'rule', rule_id: 'credential_request-v1', snippet: '인증번호를 알려주세요', start: 7, end: 18 },
      { factor_code: 'URL_REPUTATION_MATCH', label: 'URL 위협 목록의 전체 해시 일치', source: 'url_reputation', rule_id: 'verified-url-full-hash-v1', snippet: 'https://example.invalid/test', start: URL_START, end: URL_END },
    ],
    input_assessment: { status: 'action_identified', reasons: [] },
    analysis_stages: [{ name: 'rules', status: 'completed' }, { name: 'lightweight_model', status: 'completed' }, { name: 'url_reputation', status: 'completed' }],
    urls: [url],
  }
}

test('Google 근거에만 Google 표기를 붙이고 규칙 근거에는 붙이지 않는다', () => {
  render(<AnalysisResult result={result('google_safe_browsing_v5', true)} />)
  const ruleItem = screen.getByText('인증번호를 알려주세요').closest('li')!
  expect(within(ruleItem).queryByText(/Advisory provided by Google/)).toBeNull()
  const urlEvidence = screen.getAllByText('https://example.invalid/test').find(node => node.tagName === 'Q')!.closest('li')!
  const link = within(urlEvidence).getByRole('link', { name: 'Advisory provided by Google' })
  expect(link).toHaveAttribute('href', GOOGLE_ADVISORY_URL)
  // 요약 카드도 Google 경고 카드에만 표기하고 규칙 카드에는 붙이지 않는다.
  const cards = document.querySelectorAll('.evidence-item')
  const ruleCard = Array.from(cards).find(card => card.textContent?.includes('인증번호·개인정보 요구'))!
  const googleCard = Array.from(cards).find(card => card.textContent?.includes('URL 위협 목록의 전체 해시 일치'))!
  expect(within(ruleCard as HTMLElement).queryByRole('link')).toBeNull()
  expect(within(googleCard as HTMLElement).getByRole('link', { name: 'Advisory provided by Google' })).toHaveAttribute('href', GOOGLE_ADVISORY_URL)
  // 요약 카드 1개 + 상세 근거 1개 + URL 결과 1개. 모든 링크는 고정 Advisory 주소이고 사용자 URL은 링크가 아니다.
  const links = screen.getAllByRole('link')
  expect(links).toHaveLength(3)
  expect(links.every(a => a.getAttribute('href') === GOOGLE_ADVISORY_URL)).toBe(true)
})

test.each([['other_provider', true], ['google_safe_browsing_v5', false], [null, true]])(
  '공급자 %s / 전체 해시 검증 %s이면 Google 표기가 없다', (provider, verified) => {
    render(<AnalysisResult result={result(provider, verified)} />)
    expect(screen.queryByText(/Advisory provided by Google/)).toBeNull()
    expect(screen.queryAllByRole('link')).toHaveLength(0)
  })

test.each([
  ['dangerous', '위험'], ['suspicious', '의심'], ['normal', '정상'], ['insufficient_information', '정보 부족'],
] as const)('결과 제목(%s → %s)에 단계 접미사를 표시하되 정보 부족은 제외한다', (level, label) => {
  render(<AnalysisResult result={{ ...result(null, true), risk_level: level }} />)
  // 접근 이름은 aria-hidden 접미사를 무시하므로 보이는 글자 전체를 확인한다.
  expect(screen.getByRole('heading', { name: label })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(level === 'insufficient_information' ? label : `${label}단계`)
})
