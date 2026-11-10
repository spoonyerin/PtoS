import { buildShareText } from './shareResult'
import { shareFixture } from './test/shareFixture'
import { GOOGLE_ADVISORY_URL, GOOGLE_PROVIDER } from './components/GoogleAdvisory'

test('지정 형식으로 화면 요약과 대응 순서를 보존하고 원문·좌표·메타데이터는 제외한다', () => {
  const result = shareFixture()
  const text = buildShareText(result)
  expect(text).toBe(`[PtoS 분석 결과 공유]
가족과 함께 내용을 확인해 주세요.

◆ 분석 결과: 의심 단계
조금 수상한 부분이 있어요.
요청한 상대를 직접 확인하세요.

◆ 확인된 의심 요소
금전 지급 요구
금전을 보내거나 지급하라는 요구가 있어요.
송금하기 전에 상대방을 직접 확인하세요.

◆ 대응 방법
송금 전에 상대방을 확인하세요.
인증번호를 전달하지 마세요.

※ 분석 결과는 사기 여부를 확정하거나 안전을 보장하지 않습니다.
※ 개인정보 보호를 위해 입력 원문과 URL은 포함하지 않았습니다.`)
  expect(text).not.toContain('PRIVATE')
  expect(text).not.toContain('private.invalid')
  expect(text).not.toContain(result.request_id)
})

test.each(['normal', 'insufficient_information'] as const)('신호가 없는 %s의 차이를 보존한다', risk_level => {
  const text = buildShareText({ ...shareFixture(), risk_level, risk_factors: [], evidence: [] })
  expect(text).toContain(risk_level === 'normal' ? '뚜렷한 위험 신호가 없어요.' : '정상이라는 뜻은 아니에요.')
})

test('검증된 Google 경고에만 출처를 붙이고 사용자 URL은 포함하지 않는다', () => {
  const result = shareFixture()
  result.risk_factors = ['URL 위협 목록의 전체 해시 일치']
  result.evidence = [{ ...result.evidence[0], label: result.risk_factors[0], source: 'url_reputation', factor_code: 'URL_REPUTATION_MATCH' }]
  result.urls = [{ original_url: 'https://private.invalid', normalized_url: 'https://private.invalid/', ascii_host: 'private.invalid',
    validation_status: 'valid', validation_message: '', warnings: [], occurrences: [{ text: 'https://private.invalid', start: 0, end: 5 }],
    reputation: { status: 'malicious', provider: GOOGLE_PROVIDER, full_hash_verified: true, threat_types: ['MALWARE'], checked_at: null, cache_hit: false } }]
  expect(buildShareText(result)).toContain(GOOGLE_ADVISORY_URL)
  expect(buildShareText(result)).not.toContain('private.invalid')
  result.urls[0].reputation.full_hash_verified = false
  expect(buildShareText(result)).not.toContain('Advisory provided by Google')
})
