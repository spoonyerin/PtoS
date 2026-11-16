import type { AnalysisResponse } from './api/types'
import { factorDisplay } from './resultPresentation'
import { isGoogleEvidence } from './components/GoogleAdvisory'

// 화면과 같은 판단 의미를 유지하되, 듣기 편한 문장으로 안내합니다.
// 입력 원문·근거 구절·사용자 URL은 대본에 넣지 않습니다.
const introductions = {
  dangerous: '분석 결과, 위험 단계예요. 위험 신호가 발견됐어요. 요청에 응하기 전에 꼭 확인해 주세요.',
  suspicious: '분석 결과, 의심 단계예요. 수상한 부분이 있어요. 직접 확인이 필요해요.',
  normal: '분석 결과, 정상 단계예요. 현재까지 뚜렷한 위험 신호는 보이지 않아요. 그래도 안전을 보장하는 것은 아니니, 개인정보를 요구하면 주의해 주세요.',
  insufficient_information: '정보가 부족해서 아직 판단하기 어려워요. 안전하다는 뜻은 아니에요. 요청한 곳이 어디인지 별도로 확인해 주세요.',
}

export function buildSpeechSections(result: AnalysisResponse): string[] {
  const sections = [introductions[result.risk_level]]

  for (const [index, label] of result.risk_factors.entries()) {
    const evidence = result.evidence.filter(item => item.label === label)
    const description = factorDisplay[evidence[0]?.factor_code]?.description
      ?? '분석에서 확인한 신호예요. 화면의 상세 근거를 확인해 주세요.'
    // 제목과 설명을 한 번에 읽어 문장 사이에 재생이 끊기지 않게 합니다.
    sections.push([
      index === 0 ? '어떤 위험 신호가 있는지 살펴볼게요.' : '',
      `${label}.`,
      description,
      evidence.some(item => isGoogleEvidence(item, result.urls))
        ? '이 경고는 구글에서 제공한 정보예요.' : '',
    ].filter(Boolean).join(' '))
  }

  if (!result.risk_factors.length && result.risk_level !== 'normal') {
    sections.push('확인된 위험 신호는 없어요. 다만, 이것만으로 정상이라고 판단할 수는 없어요.')
  }

  const actions = [...new Set(result.action_guidance)]
  const guidance = actions.length ? actions : ['요청 출처를 별도로 확인해 주세요.']
  const ordinals = ['첫 번째로', '두 번째로', '세 번째로']
  for (const [index, text] of guidance.entries()) {
    sections.push([
      index === 0 ? '이제 어떻게 대응하면 좋을지 알려드릴게요.' : '',
      guidance.length > 1 ? `${ordinals[index] ?? `${index + 1}번째로`},` : '',
      text,
    ].filter(Boolean).join(' '))
  }

  sections.push('이 결과만으로 사기인지 확정하거나 안전을 보장할 수는 없어요. 음성 안내를 마칠게요.')

  return sections.map(text => text.replace(/https?:\/\/\S+/giu, '해당 주소'))
}
