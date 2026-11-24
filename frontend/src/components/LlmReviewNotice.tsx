import { useLlmReviewStatus } from '../hooks/useServiceStatus'

export const LLM_REVIEW_NOTICE =
  '판단이 어려운 문자는 추가 검토를 위해, 주소·전화번호·긴 숫자를 가린 문장이 외부 AI 서비스로 전송될 수 있어요.'

// 분석 요청 직전에 보이는 안내. 꺼져 있다고 확인된 경우에만 숨긴다 (확인 실패는 켜져 있을 수 있어 보인다).
export function LlmReviewNotice() {
  if (useLlmReviewStatus() === 'off') return null
  return <p className="hint url-check-notice llm-review-notice" role="note">{LLM_REVIEW_NOTICE}</p>
}
