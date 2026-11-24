import { factorDisplay } from './resultPresentation'

// API 계약의 FactorCode 값. 계약에 값이 늘면 여기와 factorDisplay를 함께 늘린다.
const factorCodes = [
  'IMPERSONATION', 'MONEY_REQUEST', 'CREDENTIAL_REQUEST', 'LINK_CLICK', 'APP_INSTALL', 'URGENCY_THREAT',
  'URL_REPUTATION_MATCH', 'CONTACT_REQUEST', 'BENEFIT_LURE', 'SECRECY_REQUEST', 'SENDER_MISMATCH',
]
const icons = ['risk-app', 'risk-credentials', 'risk-impersonation', 'risk-link', 'risk-money', 'risk-people', 'risk-urgency']

test('모든 신호 코드에 화면 설명과 있는 아이콘이 연결돼 있다', () => {
  for (const code of factorCodes) {
    expect(factorDisplay[code], code).toBeDefined()
    expect(icons).toContain(factorDisplay[code].icon)
    expect(factorDisplay[code].description.length).toBeGreaterThan(10)
  }
})

test('연락 유도·혜택·비밀 유지 설명은 단정하지 않고 확인 방법을 안내한다', () => {
  expect(factorDisplay.CONTACT_REQUEST.description).toContain('공식 연락처')
  expect(factorDisplay.BENEFIT_LURE.description).toContain('먼저 보내지 마세요')
  expect(factorDisplay.SECRECY_REQUEST.description).toContain('믿을 수 있는 사람')
})
