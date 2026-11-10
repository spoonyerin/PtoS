import type { AnalysisResponse } from './api/types'
import { riskLevels } from './riskLevels'
import { factorDisplay, resultDescriptions } from './resultPresentation'
import { GOOGLE_ADVISORY_URL, isGoogleEvidence } from './components/GoogleAdvisory'

// Only presentation summaries and action templates belong in a share. Never
// serialize the response: it contains source snippets, URLs and input metadata.
export function buildShareText(result: AnalysisResponse): string {
  const factors = result.risk_factors.map(label => {
    const evidence = result.evidence.filter(item => item.label === label)
    const description = factorDisplay[evidence[0]?.factor_code]?.description
      ?? '분석에서 확인한 신호예요. 아래 상세 근거와 행동 안내를 확인하세요.'
    const advisory = evidence.some(item => isGoogleEvidence(item, result.urls))
      ? `\n  Advisory provided by Google (Google 제공 경고)\n  ${GOOGLE_ADVISORY_URL}` : ''
    return `• ${label}\n  ${description}${advisory}`
  })
  const empty = result.risk_level === 'normal'
    ? '뚜렷한 위험 신호가 없어요.'
    : '확인된 위험 신호가 없어요. 정상이라는 뜻은 아니에요.'
  const actions = [...new Set(result.action_guidance)].map((action, i) => `${i + 1}. ${action}`)
  return [
    '[PtoS 분석 결과 공유]', '',
    '■ 분석 결과', riskLevels[result.risk_level].label,
    ...resultDescriptions[result.risk_level], '',
    '■ 확인된 의심 요소', factors.length ? factors.join('\n') : empty, '',
    '■ 대응 방법', actions.length ? actions.join('\n') : '요청 출처를 별도로 확인하세요.', '',
    '함께 내용을 확인해 주세요.', '',
    '※ 분석 결과는 사기 여부를 확정하거나 안전을 보장하지 않습니다.',
    '※ 개인정보 보호를 위해 입력 원문과 URL은 포함하지 않았습니다.',
  ].join('\n')
}
