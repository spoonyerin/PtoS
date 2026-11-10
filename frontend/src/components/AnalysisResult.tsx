import { useEffect, useRef, type ReactNode } from 'react'
import type { AnalysisResponse } from '../api/types'
import { riskLevels } from '../riskLevels'
import { UrlResults } from './UrlResults'
import { GoogleAdvisory, isGoogleEvidence } from './GoogleAdvisory'
import { factorDisplay, resultDescriptions } from '../resultPresentation'

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
  const statusIcon = {
    dangerous: 'status-danger',
    suspicious: 'status-suspicious',
    normal: 'status-normal',
    insufficient_information: 'status-insufficient',
  }[result.risk_level]
  return (
    <section
      className={`result-card ${result.risk_level}`}
      aria-labelledby="result-title"
    >
      <div className="result-banner">
        <span className="result-symbol">
          <img src={`/assets/${statusIcon}.png`} alt="" />
        </span>
        <div className="result-status-copy">
          <h2 id="result-title" ref={heading} tabIndex={-1}>
            {display.label}
            {result.risk_level !== 'insufficient_information' && (
              <small aria-hidden="true">단계</small>
            )}
          </h2>
          <p>
            {resultDescriptions[result.risk_level].map((line) => (
              <span key={line}>{line}</span>
            ))}
          </p>
        </div>
        {result.risk_level !== 'insufficient_information' && (
          <div className="risk-scale" aria-hidden="true">
            {(['normal', 'suspicious', 'dangerous'] as const).map((level, index) => {
              const current = ['normal', 'suspicious', 'dangerous'].indexOf(result.risk_level)
              return (
                <span key={level} className={`risk-scale-step${index <= current ? ' is-filled' : ''}${level === result.risk_level ? ' is-current' : ''}`}>
                  <span className="risk-scale-bar" />
                  {riskLevels[level].label}
                </span>
              )
            })}
          </div>
        )}
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
                      <img
                        src={`/assets/${signal?.icon ?? 'risk-people'}.png`}
                        alt=""
                      />
                    </span>
                    {factor}
                  </h4>
                  <p>
                    {signal?.description ??
                      '분석에서 확인한 신호예요. 아래 상세 근거와 행동 안내를 확인하세요.'}
                  </p>
                  {/* 요약 카드도 Google 자료에서 나온 경고일 때만 Google 표기를 붙인다. 상세 근거는 기본으로 접혀 있다. */}
                  {evidence.some((item) => isGoogleEvidence(item, result.urls)) && (
                    <GoogleAdvisory />
                  )}
                </li>
              )
            })}
          </ul>
        ) : (
          <div className={`empty-evidence${normal ? ' normal-empty' : ''}`}>
            <span className="empty-symbol">
              <img
                src={`/assets/${normal ? 'status-normal' : 'status-insufficient'}.png`}
                alt=""
              />
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
                  <q style={{ overflowWrap: 'anywhere' }}>{item.snippet}</q>
                  {/* Google 자료에서 나온 근거에만 Google 표기를 붙인다. 규칙 근거에는 붙이지 않는다. */}
                  {isGoogleEvidence(item, result.urls) && <GoogleAdvisory />}
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
