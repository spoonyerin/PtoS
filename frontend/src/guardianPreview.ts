import type { RiskLevel } from './api/types'

// 개발 전용 합성 데이터. 입력 원문·실제 발신 번호·공유 토큰을 저장하지 않습니다.
export type GuardianRequest = {
  senderName: string
  requestedAt: string
  summary: string
  maskedSender: string
  linkCount: number
  riskLevel: RiskLevel
  factors: { label: string; description: string; icon: string }[]
}
export const guardianPreview: GuardianRequest = {
  senderName: '엄마', requestedAt: '오늘 오전 10:01',
  summary: '택배 주소가 잘못돼 배송이 멈췄다며, 링크를 눌러 주소를 다시 입력하라는 문자예요.',
  maskedSender: '010-****-0000', linkCount: 1, riskLevel: 'dangerous',
  factors: [
    { label: '의심스러운 링크', description: '공식 사이트와 다른 주소가 발견됐어요.', icon: 'risk-link' },
    { label: '택배 회사 사칭', description: '택배 회사를 사칭한 사기 메시지와 유사해요.', icon: 'risk-impersonation' },
    { label: '개인정보 입력 유도', description: '링크에서 주소 등 개인정보를 요구할 수 있어요. 정보를 입력하지 마세요.', icon: 'risk-people' },
  ],
}
