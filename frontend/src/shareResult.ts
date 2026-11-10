import type { AnalysisResponse } from './api/types'
import { riskLevels } from './riskLevels'
import { factorDisplay, resultDescriptions } from './resultPresentation'
import { GOOGLE_ADVISORY_URL, isGoogleEvidence } from './components/GoogleAdvisory'

// Only presentation summaries and action templates belong in a share. Never
// serialize the response: it contains source snippets, URLs and input metadata.
function sentenceLines(text: string): string {
  return text.split(/(?<=[.!?])\s+/u).join('\n')
}

export function buildShareText(result: AnalysisResponse): string {
  const factors = result.risk_factors.map(label => {
    const evidence = result.evidence.filter(item => item.label === label)
    const description = factorDisplay[evidence[0]?.factor_code]?.description
      ?? '분석에서 확인한 신호예요. 아래 상세 근거와 행동 안내를 확인하세요.'
    const advisory = evidence.some(item => isGoogleEvidence(item, result.urls))
      ? `\nAdvisory provided by Google (Google 제공 경고)\n${GOOGLE_ADVISORY_URL}` : ''
    return `${label}\n${sentenceLines(description)}${advisory}`
  })
  const empty = result.risk_level === 'normal'
    ? '뚜렷한 위험 신호가 없어요.'
    : '확인된 위험 신호가 없어요. 정상이라는 뜻은 아니에요.'
  const actions = [...new Set(result.action_guidance)].map(sentenceLines)
  const level = riskLevels[result.risk_level].label
  const suffix = result.risk_level === 'insufficient_information' ? '' : ' 단계'
  return [
    '[PtoS 분석 결과 공유]', '가족과 함께 내용을 확인해 주세요.', '',
    `◆ 분석 결과: ${level}${suffix}`,
    ...resultDescriptions[result.risk_level], '',
    '◆ 확인된 의심 요소', factors.length ? factors.join('\n') : sentenceLines(empty), '',
    '◆ 대응 방법', actions.length ? actions.join('\n') : '요청 출처를 별도로 확인하세요.', '',
    '※ 분석 결과는 사기 여부를 확정하거나 안전을 보장하지 않습니다.',
    '※ 개인정보 보호를 위해 입력 원문과 URL은 포함하지 않았습니다.',
  ].join('\n')
}
