import {
  useUrlReputationStatus,
  type UrlReputationStatus,
} from '../hooks/useServiceStatus'

// 서버 상태에 맞춰 바뀌는 개발 안내. 고정 문구("아직 연결되지 않았어요")는 켜진 서버에서 거짓이 된다.
// 준비 상태는 모델 연결 여부를 알려주지 않으므로 모델은 단정하지 않는다.
const reputationNote: Record<UrlReputationStatus, string> = {
  live: 'URL 평판 조회(Google Safe Browsing)는 켜져 있지만',
  off: 'URL 평판 조회는 꺼져 있으며',
  unknown: 'URL 평판 조회가 켜져 있는지 확인하지 못했으며',
}

export function developmentNoteText(status: UrlReputationStatus): string {
  return `일부 분석 단계는 꺼져 있을 수 있고 ${reputationNote[status]}, 결과는 안전을 보장하지 않아요.`
}

export function DevelopmentNote() {
  const status = useUrlReputationStatus()
  return (
    <p className="development-note">
      규칙 기반 개발 버전 · {developmentNoteText(status)}
    </p>
  )
}
