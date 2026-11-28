import type { AnalysisRequest, AnalysisResponse, ReadyResponse, RiskLevel } from './types'
import { factorDisplay } from '../resultPresentation'
export class AnalysisError extends Error {}
let scenario: RiskLevel = 'dangerous'
export function setPreviewScenario(next: RiskLevel) { scenario = next }
export async function requestServiceStatus(_signal: AbortSignal): Promise<ReadyResponse> {
  return { status: 'ready', mode: 'rules', url_reputation: 'off', llm_review: 'off', family: 'off', push: 'off' }
}
export async function requestAnalysis(_body: AnalysisRequest, signal: AbortSignal): Promise<AnalysisResponse> {
  if (signal.aborted) throw new DOMException('cancelled', 'AbortError')
  // 입력을 분류하지 않습니다. 개발자가 고른 시나리오의 합성 결과만 만듭니다.
  const hasSignals = scenario === 'dangerous' || scenario === 'suspicious'
  const signals = hasSignals ? [
    { factor_code: 'IMPERSONATION' as const, label: '기관·지인 명의 주장' },
    { factor_code: 'CREDENTIAL_REQUEST' as const, label: '인증번호·개인정보 요구' },
    { factor_code: 'LINK_CLICK' as const, label: '링크 클릭·접속 요구' },
  ] : []
  return {
    request_id: crypto.randomUUID(), risk_level: scenario, confidence: null,
    risk_factors: signals.map(s => s.label), explanation: '개발용 UI 예시 결과입니다. 입력 내용의 실제 분석 결과가 아닙니다.',
    action_guidance: signals.length ? ['문자 속 링크를 누르지 말고 공식 앱에서 확인하세요.', '출처를 확인하기 전에는 개인정보를 입력하지 마세요.'] : ['요청 출처를 별도로 확인해 주세요.'],
    limitations: ['UI 미리보기 · 실제 판정 아님'], analysis_version: 'ui-preview-local', policy_reason: 'UI_PREVIEW_ONLY',
    is_demo: false, analysis_mode: 'rules',
    evidence: signals.map(s => ({ ...s, source: 'rule', rule_id: `ui-preview-${s.factor_code}`, snippet: factorDisplay[s.factor_code].description, start: 0, end: 1 })),
    input_assessment: { status: hasSignals ? 'action_identified' : 'sentence_present', reasons: [] },
    analysis_stages: [{ name: 'rules', status: 'not_implemented' }], urls: [],
  }
}
