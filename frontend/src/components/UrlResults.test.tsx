import { render, screen } from '@testing-library/react'
import type { UrlFinding } from '../api/types'
import { UrlResults } from './UrlResults'
import { GOOGLE_ADVISORY_URL } from './GoogleAdvisory'

function finding(status: UrlFinding['reputation']['status']): UrlFinding {
  return {
    original_url: 'https://예시.한국/공지?private=token', normalized_url: 'https://xn--vv4b11d.xn--3e0b707e/', ascii_host: 'xn--vv4b11d.xn--3e0b707e',
    validation_status: 'valid', validation_message: '주소 형식만 확인했어요.', warnings: [], occurrences: [],
    reputation: { status, provider: 'google_safe_browsing_v5', checked_at: null, full_hash_verified: false, cache_hit: false },
  }
}

test.each([
  ['unknown', '안전 판정 아님'], ['auth_error', '인증 오류'],
  ['rate_limited', '호출 제한'], ['timeout', '시간 초과'], ['unavailable', '조회 장애'],
] as const)('가짜 평판 상태 %s를 구별하고 URL은 클릭되지 않는다', (status, label) => {
  const { container } = render(<UrlResults urls={[finding(status)]} />)
  expect(screen.getByText(new RegExp(label))).toBeVisible()
  expect(screen.getByText('평판 조회 공급자: Google Safe Browsing')).toBeVisible()
  expect(container.querySelector('a, img, iframe')).toBeNull()
})

test('가짜 전체 해시 일치의 유형·조회 시각·캐시와 주의 문구를 표시한다', () => {
  const url = finding('malicious')
  url.reputation = { ...url.reputation, full_hash_verified: true, threat_types: ['SOCIAL_ENGINEERING'], checked_at: '2026-10-23T00:00:00Z', cache_hit: true }
  render(<UrlResults urls={[url]} />)
  expect(screen.getByText(/전체 SHA-256 해시 일치/)).toBeVisible()
  expect(screen.getByText(/SOCIAL_ENGINEERING/)).toBeVisible()
  expect(screen.getByText(/캐시 사용/)).toBeVisible()
  expect(screen.getByText(/안전을 보장하지 않아요/)).toBeVisible()
})

test('조건 확인 전 보류 상태와 개발 호출 예산을 구분한다', () => {
  const held = finding('not_connected')
  held.reputation.reason = 'policy_pending'
  const limited = finding('rate_limited')
  limited.reputation.reason = 'local_limit'
  render(<UrlResults urls={[held, limited]} />)
  expect(screen.getByText(/외부 조회가 꺼져 있어요/)).toBeVisible()
  expect(screen.getByText(/개발용 로컬 호출 예산/)).toBeVisible()
})

test.each([
  ['network_error', '네트워크 문제로'], ['server_error', '평판 조회 서버에 문제가'], ['http_error', '요청이 처리되지 않았어요'],
  ['invalid_response', '응답을 읽지 못했어요'], ['invalid_config', '설정이 올바르지 않아'], ['not_configured', '설정되지 않아'],
  ['key_missing', '설정되지 않아'],
])('reason %s를 쉬운 문장으로 설명한다', (reason, text) => {
  const url = finding(reason.endsWith('_config') || reason.endsWith('configured') || reason === 'key_missing' ? 'not_connected' : 'unavailable')
  url.reputation.reason = reason
  render(<UrlResults urls={[url]} />)
  expect(screen.getByText(new RegExp(text))).toBeVisible()
})

test('Google 전체 해시 경고에만 고정 Advisory 링크 하나를 붙이고 사용자 URL은 링크로 만들지 않는다', () => {
  const url = finding('malicious')
  url.reputation = { ...url.reputation, full_hash_verified: true, threat_types: ['MALWARE'] }
  const { container } = render(<UrlResults urls={[url]} />)
  expect(screen.getByText('위험한 사이트일 수 있다는 보고가 있어요', { exact: false })).toBeVisible()
  expect(screen.getByText(/위험한 사이트를 놓치거나 안전한 사이트를 위험으로 잘못 표시할 수 있어요/)).toBeVisible()
  const links = container.querySelectorAll('a')
  expect(links).toHaveLength(1)
  expect(links[0]).toHaveAttribute('href', GOOGLE_ADVISORY_URL)
  expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer')
  expect(links[0]).toHaveTextContent('Advisory provided by Google')
  expect(container.querySelector('img, iframe')).toBeNull()
})

test.each([
  ['다른 공급자의 일치', 'other_provider', true],
  ['전체 해시 미검증', 'google_safe_browsing_v5', false],
])('%s에는 Google 표기를 붙이지 않는다', (_name, provider, verified) => {
  const url = finding('malicious')
  url.reputation = { ...url.reputation, provider, full_hash_verified: verified }
  const { container } = render(<UrlResults urls={[url]} />)
  expect(container.querySelector('a')).toBeNull()
  expect(screen.queryByText(/Advisory provided by Google/)).toBeNull()
})
