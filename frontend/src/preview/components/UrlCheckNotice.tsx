import { useUrlReputationStatus } from '../hooks/useServiceStatus'

// 분석 요청 직전에 보이는 안내. 꺼져 있다고 확인된 경우에만 숨긴다 (확인 실패는 켜져 있을 수 있어 보인다).
export function UrlCheckNotice() {
  if (useUrlReputationStatus() === 'off') return null
  return <p className="hint url-check-notice" role="note">
    URL 확인 기능이 켜져 있어요. 주소를 그대로 보내지 않고, 주소에서 만든 일부 정보(해시)만 Google로 전송돼요.
  </p>
}
