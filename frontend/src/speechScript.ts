import type { AnalysisResponse } from './api/types'
import { isGoogleEvidence } from './components/GoogleAdvisory'

// 자유 형식 설명·라벨·원문·연락처는 읽지 않습니다. 분석된 코드에 대응하는
// 검수 문장만 조합하며, 코드 자체로 기관·업종·악성 여부를 추정하지 않습니다.
const signals = {
  URL_REPUTATION_MATCH: '위협 목록과 일치하는 링크가 발견됐어요.',
  CREDENTIAL_REQUEST: '인증번호나 개인정보를 알려주거나 입력하라는 요구가 있어요.',
  MONEY_REQUEST: '돈을 보내거나 지급하라는 요구가 있어요.',
  APP_INSTALL: '앱이나 프로그램을 설치하거나 실행하라는 요구가 있어요.',
  IMPERSONATION: '기관이나 지인의 명의를 내세운 표현이 있어요. 실제 발신자가 맞는지는 확인되지 않았어요.',
  LINK_CLICK: '링크를 누르거나 주소에 접속하라는 요구가 있어요. 이 요구만으로 수상한 주소인지 확정할 수는 없어요.',
  URGENCY_THREAT: '빠른 처리를 재촉하거나 불이익을 언급하는 표현이 있어요.',
}
type Signal = keyof typeof signals
const introductions = {
  dangerous: '분석 결과, 위험 단계입니다.',
  suspicious: '분석 결과, 의심 단계입니다. 아직 사기라고 확정할 수는 없지만, 확인이 필요해요.',
  normal: '분석 결과, 정상 단계입니다. 이번 검사에서는 뚜렷한 위험 신호를 찾지 못했어요. 다만, 안전이 보장되는 것은 아니에요.',
  insufficient_information: '분석할 정보가 부족해요. 지금은 이 메시지가 위험한지 판단하기 어려워요.',
}

export function buildSpeechSections(result: AnalysisResponse, { canRecheck = true } = {}): string[] {
  const sections = [introductions[result.risk_level]]
  if (result.risk_level === 'normal') return [...sections,
    '돈을 보내거나 개인정보를 입력해 달라는 요청이 있다면, 먼저 상대방이 맞는지 따로 확인해 주세요.',
    '메시지에 적힌 연락처 대신, 평소 알고 있던 연락처나 공식 홈페이지에서 확인해 주세요.',
  ]

  const found = new Set(result.evidence.filter(item => result.risk_factors.includes(item.label)).map(item => item.factor_code))
  // 위협 목록 경고는 전체 해시가 실제 일치한 평판 근거가 있을 때만 읽습니다.
  if (!result.urls.some(url => url.reputation.status === 'malicious' && url.reputation.full_hash_verified)) found.delete('URL_REPUTATION_MATCH')
  const selected = (Object.keys(signals) as Signal[]).filter(code => found.has(code)).slice(0, 2)
  if (selected.length) sections.push(selected.map(code => signals[code]).join(' ') + (
    selected.includes('URL_REPUTATION_MATCH') && result.evidence.some(item => isGoogleEvidence(item, result.urls))
      ? ' 이 경고는 구글에서 제공한 정보예요.' : ''))

  const actions: string[] = []
  if (selected.some(code => code === 'LINK_CLICK' || code === 'URL_REPUTATION_MATCH')) actions.push('확인 전에는 링크를 누르지 마세요.')
  if (selected.includes('CREDENTIAL_REQUEST')) actions.push('확인 전에는 인증번호나 개인정보를 알려주거나 입력하지 마세요.')
  if (selected.includes('MONEY_REQUEST')) actions.push('상대방이 확인되기 전에는 돈을 보내지 마세요.')
  if (selected.includes('APP_INSTALL')) actions.push('출처를 확인하기 전에는 안내받은 앱을 설치하거나 실행하지 마세요.')
  if (!actions.length) actions.push(result.risk_level === 'insufficient_information'
    ? '확인 전에는 링크를 누르거나 개인정보를 입력하지 마세요.'
    : '요청에 바로 따르지 말고, 상대방이 맞는지 먼저 확인해 주세요.')
  sections.push(actions.join(' '))
  sections.push(result.risk_level === 'insufficient_information' && canRecheck
    ? '메시지 내용이 빠져 있다면, 전체 내용이 보이도록 다시 검사해 주세요.'
    : selected.includes('IMPERSONATION') || selected.includes('MONEY_REQUEST')
      ? '문자에 적힌 연락처 대신, 직접 확인한 공식 연락처나 평소 알고 있던 번호로 확인해 주세요.'
      : '메시지 속 링크 대신, 평소 사용하는 공식 앱이나 공식 홈페이지에서 따로 확인해 주세요.')
  if (result.risk_level === 'insufficient_information' && !canRecheck) sections[sections.length - 1] = '메시지를 보낸 곳의 공식 연락처로 따로 확인해 주세요.'
  return sections
}
