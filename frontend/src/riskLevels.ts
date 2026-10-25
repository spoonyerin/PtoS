import type { RiskLevel } from './api/types'

// normal은 계약 호환용이다. 현재 규칙 정책에서는 반환하지 않는다.
export const riskLevels: Record<RiskLevel, { label: string; symbol: string }> = {
  normal: { label: '정상', symbol: '✓' },
  suspicious: { label: '의심', symbol: '!' },
  dangerous: { label: '위험', symbol: '⚠' },
  insufficient_information: { label: '정보 부족', symbol: '?' },
}
