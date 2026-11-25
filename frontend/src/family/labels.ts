import type { FactorCode, FamilyRelation, FamilyReplyChoice, FamilyRequestItem } from '../api/family'

export const relationLabels: Record<FamilyRelation, string> = {
  child: '자식',
  spouse: '배우자',
  sibling: '형제·자매',
  other: '기타',
}

// 확인 요청에는 위험 요소 코드만 있다. 이름은 분석 결과 화면과 같은 표현을 쓴다.
export const factorLabels: Record<FactorCode, string> = {
  IMPERSONATION: '기관·지인 명의 주장',
  MONEY_REQUEST: '금전 지급 요구',
  CREDENTIAL_REQUEST: '인증번호·개인정보 요구',
  LINK_CLICK: '링크 클릭·접속 요구',
  APP_INSTALL: '앱 설치·실행 요구',
  URGENCY_THREAT: '긴급성·불이익 압박 표현',
  CONTACT_REQUEST: '전화·답장 등 연락 유도',
  BENEFIT_LURE: '혜택·당첨 안내',
  SECRECY_REQUEST: '비밀 유지 요구',
  SENDER_MISMATCH: '보낸 번호와 기관 이름 불일치',
  URL_REPUTATION_MATCH: '위협 목록과 일치한 주소',
}

export const replyLabels: Record<Exclude<FamilyReplyChoice, 'custom'>, string> = {
  looks_dangerous: '위험해 보여요.',
  looks_fine: '문제 없어 보여요.',
}

export function replyText(reply: NonNullable<FamilyRequestItem['reply']>): string {
  return reply.choice === 'custom' ? reply.text ?? '' : replyLabels[reply.choice]
}

const timeFormat = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : timeFormat.format(date)
}

export function initial(name: string): string {
  return Array.from(name.trim())[0] ?? '가'
}
