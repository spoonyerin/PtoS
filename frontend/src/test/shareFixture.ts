import type { AnalysisResponse } from '../api/types'
export function shareFixture(): AnalysisResponse {
  return {
    request_id: '8c224149-d5c4-4f9a-a77b-55a058cb8c71', risk_level: 'suspicious', confidence: null,
    risk_factors: ['금전 지급 요구'], explanation: '입력 원문 PRIVATE 010-1234-5678',
    action_guidance: ['송금 전에 상대방을 확인하세요.', '인증번호를 전달하지 마세요.', '송금 전에 상대방을 확인하세요.'],
    limitations: [], analysis_version: 'rules-model-dev-v1', is_demo: false, analysis_mode: 'rules',
    policy_reason: 'REQUEST_IDENTIFIED', urls: [],
    evidence: [{ factor_code: 'MONEY_REQUEST', label: '금전 지급 요구', source: 'rule', rule_id: 'money_request-v1',
      snippet: 'PRIVATE 원문 https://private.invalid/?secret=123', start: 0, end: 5 }],
    input_assessment: { status: 'action_identified', reasons: [] },
    analysis_stages: [{ name: 'rules', status: 'completed' }],
  }
}
