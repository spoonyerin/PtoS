import type { AnalysisResponse } from './api/types'
import { riskLevels } from './riskLevels'
import { factorDisplay, resultDescriptions } from './resultPresentation'
import { isGoogleEvidence } from './components/GoogleAdvisory'

// 입력 원문이나 근거 구절 대신 화면의 요약 템플릿을 사용합니다.
export function buildSpeechSections(result: AnalysisResponse): string[] {
  const level = riskLevels[result.risk_level].label
  const sections = [
    result.risk_level === 'insufficient_information'
      ? '분석 결과, 정보 부족입니다. 안전하다는 뜻은 아닙니다.'
      : `분석 결과, ${level} 단계입니다.`,
    ...resultDescriptions[result.risk_level],
  ]

  if (result.risk_factors.length) {
    sections.push('확인된 위험 요소를 안내해 드리겠습니다.')

    for (const label of result.risk_factors) {
      const evidence = result.evidence.filter(item => item.label === label)

      sections.push(
        `${label}.`,
        factorDisplay[evidence[0]?.factor_code]?.description
          ?? '분석에서 확인한 신호입니다. 화면의 상세 근거를 확인해 주세요.',
      )

      if (evidence.some(item => isGoogleEvidence(item, result.urls))) {
        sections.push('구글 제공 경고입니다.')
      }
    }
  } else {
    sections.push(
      result.risk_level === 'normal'
        ? '뚜렷한 위험 신호가 발견되지 않았습니다.'
        : '확인된 위험 신호는 없지만, 정상이라는 뜻은 아닙니다.',
    )
  }

  sections.push('이어서 대응 방법을 안내해 드리겠습니다.')

  const actions = [...new Set(result.action_guidance)]
  sections.push(
    ...(actions.length
      ? actions.map((text, index) => `${index + 1}번째, ${text}`)
      : ['요청 출처를 별도로 확인해 주세요.']),
  )

  sections.push(
    '분석 결과는 사기 여부를 확정하거나 안전을 보장하지 않습니다. 음성 안내를 마칩니다.',
  )

  return sections.map(text =>
    text.replace(/https?:\/\/\S+/giu, '해당 주소'),
  )
}
