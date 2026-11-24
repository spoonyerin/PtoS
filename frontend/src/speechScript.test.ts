import { expect, test } from 'vitest'
import { buildSpeechSections } from './speechScript'
import { shareFixture } from './test/shareFixture'
import type { AnalysisResponse } from './api/types'
const fixture = shareFixture()
const withCodes = (codes: AnalysisResponse['evidence'][number]['factor_code'][]): AnalysisResponse => ({
  ...fixture, risk_factors: codes, evidence: codes.map(code => ({ ...fixture.evidence[0], factor_code: code, label: code })),
})

test.each([
  ['dangerous', '분석 결과, 위험 단계입니다.'],
  ['suspicious', '분석 결과, 의심 단계입니다.'],
  ['normal', '분석 결과, 정상 단계입니다.'],
  ['insufficient_information', '분석할 정보가 부족해요.'],
] as const)('%s는 결과부터 말하며 원문·주소·번호·자유 설명을 읽지 않는다', (level, introduction) => {
  const text = buildSpeechSections({ ...fixture, risk_level: level,
    action_guidance: ['https://secret.invalid/PRIVATE', '010-1234-5678', 'someone@example.com', '주민번호 901010-1234567'],
  }).join(' ')
  expect(text.startsWith(introduction)).toBe(true)
  expect(text).not.toMatch(/PRIVATE|secret|010-1234|someone|901010|가족에게 공유|홈으로|눈금/)
})

test('검증된 주요 이유 두 개만 고정 우선순위로 선택하고 행동을 연결한다', () => {
  const sections = buildSpeechSections(withCodes(['URGENCY_THREAT', 'IMPERSONATION', 'LINK_CLICK', 'CREDENTIAL_REQUEST', 'MONEY_REQUEST']))
  expect(sections).toHaveLength(4)
  expect(sections[1]).toContain('인증번호나 개인정보')
  expect(sections[1]).toContain('돈을 보내거나')
  expect(sections[1]).not.toMatch(/빠른 처리|명의|링크/)
  expect(sections[2]).toContain('입력하지 마세요')
  expect(sections[2]).toContain('돈을 보내지 마세요')
  expect(sections[3]).toContain('평소 알고 있던 번호')
})

test('명의 주장만으로 택배 사칭을 단정하지 않고 링크 요구를 악성 링크로 바꾸지 않는다', () => {
  const sections = buildSpeechSections(withCodes(['IMPERSONATION', 'LINK_CLICK']))
  expect(sections[1]).toContain('실제 발신자가 맞는지는 확인되지 않았어요')
  expect(sections.join(' ')).not.toMatch(/택배|사칭한|악성 링크|위협 목록/)
  expect(sections[2]).toContain('링크를 누르지 마세요')
})

test('실제 근거가 없는 라벨이나 설명을 읽지 않는다', () => {
  const sections = buildSpeechSections({ ...fixture, evidence: [], risk_factors: ['택배 사칭 010-1234-5678'] })
  expect(sections.join(' ')).not.toMatch(/택배|010-|돈을 보내라는 요구/)
})

test('중복 근거는 한 번만 안내하며 앱 설치는 출처 확인을 먼저 안내한다', () => {
  const result = withCodes(['APP_INSTALL', 'APP_INSTALL'])
  const sections = buildSpeechSections(result)
  expect(sections[1].match(/앱이나 프로그램/g)).toHaveLength(1)
  expect(sections[2]).toContain('설치하거나 실행하지 마세요')
})

test('정상도 안전 보장이 아니며 모순된 위험 근거를 읽지 않는다', () => {
  const text = buildSpeechSections({ ...fixture, risk_level: 'normal' }).join(' ')
  expect(text).toContain('안전이 보장되는 것은 아니에요')
  expect(text).toContain('요청이 있다면')
  expect(text).not.toContain('돈을 보내거나 지급하라는 요구가 있어요')
})

test('정보 부족은 판단 불가와 재검사 또는 공식 연락처 확인을 안내한다', () => {
  const result = { ...fixture, risk_level: 'insufficient_information' as const, evidence: [], risk_factors: [] }
  expect(buildSpeechSections(result).join(' ')).toContain('판단하기 어려워요')
  expect(buildSpeechSections(result).at(-1)).toContain('다시 검사해 주세요')
  expect(buildSpeechSections(result, { canRecheck: false }).at(-1)).toBe('메시지를 보낸 곳의 공식 연락처로 따로 확인해 주세요.')
})

test('검증되지 않은 URL 평판 근거는 위협 목록 일치로 읽지 않는다', () => {
  expect(buildSpeechSections(withCodes(['URL_REPUTATION_MATCH'])).join(' ')).not.toContain('위협 목록')
})

test('검증된 Google 평판 경고에는 출처를 붙이되 실제 주소는 읽지 않는다', () => {
  const result = withCodes(['URL_REPUTATION_MATCH'])
  result.evidence[0].source = 'url_reputation'
  result.urls = [{ original_url: 'https://private.invalid', normalized_url: 'https://private.invalid/', ascii_host: 'private.invalid',
    validation_status: 'valid', validation_message: '', warnings: [], occurrences: [{ text: 'https://private.invalid', start: 0, end: 5 }],
    reputation: { status: 'malicious', provider: 'google_safe_browsing_v5', full_hash_verified: true, threat_types: ['MALWARE'], checked_at: null, cache_hit: false } }]
  expect(buildSpeechSections(result).join(' ')).toContain('구글에서 제공한 정보예요')
  expect(buildSpeechSections(result).join(' ')).not.toContain('private.invalid')
  result.urls[0].reputation.full_hash_verified = false
  expect(buildSpeechSections(result).join(' ')).not.toMatch(/위협 목록|구글/)
})
