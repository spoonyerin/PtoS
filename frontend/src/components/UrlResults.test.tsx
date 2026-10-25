import { render, screen } from '@testing-library/react'
import type { UrlFinding } from '../api/types'
import { UrlResults } from './UrlResults'

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
  expect(screen.getByText(/이용 조건 확인 전/)).toBeVisible()
  expect(screen.getByText(/개발용 로컬 호출 예산/)).toBeVisible()
})
