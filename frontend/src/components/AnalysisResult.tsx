import { useEffect, useRef } from 'react'
import type { AnalysisResponse } from '../api/types'
import { riskLevels } from '../riskLevels'
import { UrlResults } from './UrlResults'

export function AnalysisResult({ result }: { result: AnalysisResponse }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const display = riskLevels[result.risk_level]
  useEffect(() => { heading.current?.focus() }, [result.request_id])
  return (
    <section className={`card result-card ${result.risk_level}`} aria-labelledby="result-title">
      <div className="section-kicker">02 · 결과 확인</div>
      <p className="demo-badge">규칙 기반 개발 버전</p>
      <h2 id="result-title" ref={heading} tabIndex={-1}><span className="result-symbol" aria-hidden="true">{display.symbol}</span>{display.label}</h2>
      <p className="result-explanation">{result.explanation}</p>
      <div className="result-section">
        <h3>입력에서 확인한 표현</h3>
        {result.risk_factors.length ? <ul>{result.risk_factors.map(factor => <li key={factor}>
          {factor}
          <ul>{result.evidence.filter(item => item.label === factor).map(item => <li key={`${item.rule_id}-${item.start}-${item.end}`}><q style={{ overflowWrap: 'anywhere' }}>{item.snippet}</q></li>)}</ul>
        </li>)}</ul> : <p>현재 규칙으로 확인한 위험 요구는 없어요. 정상이라는 뜻은 아니에요.</p>}
      </div>
      <UrlResults urls={result.urls} />
      <div className="result-section actions">
        <h3>이렇게 행동하세요</h3>
        <ol>{result.action_guidance.map(action => <li key={action}>{action}</li>)}</ol>
      </div>
      <div className="result-limitations">{result.limitations.map(text => <p key={text}>{text}</p>)}</div>
    </section>
  )
}
