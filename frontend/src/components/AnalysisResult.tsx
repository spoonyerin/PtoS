import { useEffect, useRef, type ReactNode } from 'react'
import type { AnalysisResponse } from '../api/types'
import { riskLevels } from '../riskLevels'
import { UrlResults } from './UrlResults'
import { Icon, type IconName } from './Icons'

// These describe signals supplied by the API, not additional classifications.
const factorDisplay: Record<string, { icon: IconName; description: string }> = {
  IMPERSONATION: {
    icon: 'institution',
    description:
      '기관이나 지인의 명의를 내세운 표현이 있어요. 실제 발신자인지는 공식 연락처로 확인하세요.',
  },
  MONEY_REQUEST: {
    icon: 'message',
    description:
      '금전을 보내거나 지급하라는 요구가 있어요. 송금하기 전에 상대방을 직접 확인하세요.',
  },
  CREDENTIAL_REQUEST: {
    icon: 'people',
    description:
      '인증번호나 개인정보를 전달·입력하라는 요구가 있어요. 요청 출처를 별도로 확인하세요.',
  },
  LINK_CLICK: {
    icon: 'link',
    description:
      '링크를 누르거나 주소에 접속하라는 표현이 있어요. 주소를 열기 전에 공식 경로로 확인하세요.',
  },
  APP_INSTALL: {
    icon: 'photo',
    description:
      '앱이나 프로그램을 설치·실행하라는 요구가 있어요. 공식 배포처와 요청 출처를 확인하세요.',
  },
  URGENCY_THREAT: {
    icon: 'warning',
    description:
      '빠른 처리를 재촉하거나 불이익을 언급하는 표현이 있어요. 서두르지 말고 요청을 확인하세요.',
  },
  URL_REPUTATION_MATCH: {
    icon: 'link',
    description:
      'URL의 전체 해시가 위협 목록과 일치했어요. 링크를 누르지 마세요.',
  },
}
export function AnalysisResult({
  result,
  children,
}: {
  result: AnalysisResponse
  children?: ReactNode
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const display = riskLevels[result.risk_level]
  const normal = result.risk_level === 'normal'
  useEffect(() => {
    heading.current?.focus()
  }, [result.request_id])
  const descriptions = {
    dangerous: '이 메시지는 위험해 보여요. 조심하세요.',
    suspicious: '조금 수상한 부분이 있어요. 확인해 보세요.',
    normal: '현재까지는 위험한 요소가 보이지 않아요.',
    insufficient_information: '정보가 부족해서 아직 알기 어려운 상태예요.',
  }
  const statusIcon: IconName = normal
    ? 'safe'
    : result.risk_level === 'dangerous'
      ? 'ban'
      : result.risk_level === 'suspicious'
        ? 'warning'
        : 'uncertain'
  return (
    <section
      className={`result-card ${result.risk_level}`}
      aria-labelledby="result-title"
    >
      <div className="result-banner">
        <span className="result-symbol">
          <Icon name={statusIcon} />
        </span>
        <div className="result-status-copy">
          <h2 id="result-title" ref={heading} tabIndex={-1}>
            {display.label}
            <small aria-hidden="true">단계</small>
          </h2>
          <p>{descriptions[result.risk_level]}</p>
        </div>
      </div>
      <div className="result-section result-findings">
        <h3>발견된 위험 요소</h3>
        {result.risk_factors.length ? (
          <ul className="evidence-list">
            {result.risk_factors.map((factor) => {
              const evidence = result.evidence.filter(
                (item) => item.label === factor,
              )
              const signal = factorDisplay[evidence[0]?.factor_code]
              return (
                <li className="evidence-item" key={factor}>
                  <h4 className="evidence-title">
                    <span className="factor-symbol">
                      <Icon name={signal?.icon ?? 'message'} />
                    </span>
                    {factor}
                  </h4>
                  <p>
                    {signal?.description ??
                      '분석에서 확인한 신호예요. 아래 상세 근거와 행동 안내를 확인하세요.'}
                  </p>
                </li>
              )
            })}
          </ul>
        ) : (
          <div className={`empty-evidence${normal ? ' normal-empty' : ''}`}>
            <span className="empty-symbol">
              <Icon name={normal ? 'check' : 'uncertain'} />
            </span>
            <strong>
              {normal
                ? '뚜렷한 위험 신호가 없어요.'
                : '확인된 위험 신호가 없어요.'}
            </strong>
            <p>
              {normal
                ? '다만 새로운 사기 수법일 수 있으니 개인정보를 요구하는 경우에는 주의해 주세요.'
                : '정보가 부족해서 아직 판단하기 어려워요. 정상이라는 뜻은 아니에요.'}
            </p>
          </div>
        )}
      </div>
      {children}
      <details className="result-details">
        <summary>분석 근거와 행동 안내 자세히 보기</summary>
        <p className="result-explanation">{result.explanation}</p>
        {result.evidence.length > 0 && (
          <section className="result-section">
            <h3>입력에서 확인한 표현</h3>
            <ul className="source-evidence">
              {result.evidence.map((item) => (
                <li key={`${item.rule_id}-${item.start}-${item.end}`}>
                  <strong>{item.label}</strong>
                  <q>{item.snippet}</q>
                </li>
              ))}
            </ul>
          </section>
        )}
        <UrlResults urls={result.urls} />
        <div className="result-section actions">
          <h3>이렇게 행동하세요</h3>
          <ol>
            {result.action_guidance.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
        </div>
        <p className="development-note">규칙 기반 개발 버전</p>
        <div className="result-limitations">
          {result.limitations.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      </details>
      <p className="result-disclaimer">
        규칙 기반 개발 버전 · 결과는 안전을 보장하지 않아요.
      </p>
    </section>
  )
}
